import os
import sys
import datetime
import numpy as np
import csv
import logging
import logging.handlers
import pandas as pd

from tqdm import tqdm
from dragen.generation.DiscreteRsa3D import DiscreteRsa3D
from dragen.generation.DiscreteTesselation3D import Tesselation3D
from dragen.utilities.RVE_Utils import RVEUtils
from dragen.generation.mesher import Mesher

from InputGenerator.C_WGAN_GP import WGANCGP
from InputGenerator.linking import Reconstructor

class DataTask3D:

    def __init__(self, box_size=30, n_pts=50, number_of_bands=0, bandwidth=3, shrink_factor=0.5,
                 file1=None, file2=None, store_path=None,
                 gui_flag=True, anim_flag=False, gan_flag=False, exe_flag=False, inclusions_flag=True,
                 band_filling=0.99, phase_ratio=0.95, inclusions_ratio=0.01):
        self.logger = logging.getLogger("RVE-Gen")
        self.box_size = box_size
        self.n_pts = n_pts  # has to be even
        self.bin_size = self.box_size / self.n_pts
        self.step_half = self.bin_size / 2
        self.shrink_factor = np.cbrt(shrink_factor)
        self.gui_flag = gui_flag
        self.gan_flag = gan_flag
        self.inclusions_flag = inclusions_flag if self.gan_flag else False  # geht nicht ohne GAN
        self.root_dir = './'

        """
        Aktueller Parametersatz für GAN:
        Parameters:
                 
        
        """
        self.number_of_bands = number_of_bands
        self.bandwidth = bandwidth
        self.band_filling = band_filling           # Percentage of Filling for the banded structure
        self.phase_ratio = phase_ratio            # 1 means all ferrite, 0 means all Martensite
        self.inclusion_ratio = inclusions_ratio        # Space occupied by inclusions

        if exe_flag:
            self.root_dir = store_path
        if not gui_flag:
            self.root_dir = sys.argv[0][:-14]  # setting root_dir to root_dir by checking path of current file
        elif gui_flag and not exe_flag:
            self.root_dir = store_path

        self.logger.info('the exe_flag is: ' + str(exe_flag))
        self.logger.info('root was set to: ' + self.root_dir)
        self.animation = anim_flag
        self.file1 = file1
        self.file2 = file2
        self.utils_obj = RVEUtils(self.box_size, self.n_pts, self.bandwidth)
        if self.gan_flag:
            self.GAN = self.run_cwgangp()

    # Läuft einen Trainingsdurchgang und erzeugt ein GAN-Object
    def run_cwgangp(self):
        SOURCE = self.root_dir + '/ExampleInput'

        # Data:
        df1 = pd.read_csv(SOURCE + '/Input_TDxBN_AR.csv')
        df2 = pd.read_csv(SOURCE + '/Input_RDxBN_AR.csv')
        df3 = pd.read_csv(SOURCE + '/Input_RDxTD_AR.csv')

        # Inclusions
        df4 = pd.read_csv(SOURCE + '/Einschlüsse_TDxBN_AR.csv')
        df5 = pd.read_csv(SOURCE + '/Einschlüsse_RDxBN_AR.csv')
        df6 = pd.read_csv(SOURCE + '/Einschlüsse_RDxTD_AR.csv')

        # Set up CWGAN-GP with all data
        store_path = self.root_dir + '/OutputData/' + str(datetime.datetime.now())[:10] + '_' + str(0)
        if not os.path.isdir(store_path):
            os.makedirs(store_path)
        GAN = WGANCGP(df_list=[df1, df2, df3, df4, df5, df6], storepath=store_path, num_features=3, gen_iters=100)

        # Run training for 5000 Its - 150.000 is default
        # GAN.train()

        # Evaluate Afterwards
        # GAN.evaluate()
        self.logger.info('Created GAN-Object successfully!')

        return GAN

    def sample_gan_input(self, adjusted_size, labels=(), size=1000, maximum=None):
        TDxBN = self.GAN.sample_batch(label=labels[0], size=size * 2)
        RDxBN = self.GAN.sample_batch(label=labels[1], size=size * 2)
        RDxTD = self.GAN.sample_batch(label=labels[2], size=size * 2)

        # Run the Reconstruction
        Bot = Reconstructor(TDxBN, RDxBN, RDxTD, drop=True)
        Bot.run(n_points=size)  # Could take a while with more than 500 points...

        # Calculate the Boxsize based on Bands and original size
        adjusted_size = adjusted_size
        print('Adjusted Size:', adjusted_size)
        Bot.get_rve_input(bs=adjusted_size, maximum=maximum)
        return Bot.rve_inp  # This is the RVE-Input data

    def setup_logging(self):
        LOGS_DIR = self.root_dir + '/Logs/'
        if not os.path.isdir(LOGS_DIR):
            os.makedirs(LOGS_DIR)
        f_handler = logging.handlers.TimedRotatingFileHandler(
            filename=os.path.join(LOGS_DIR, 'dragen-logs'), when='midnight')
        formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s')
        f_handler.setFormatter(formatter)
        self.logger.addHandler(f_handler)
        self.logger.setLevel(level=logging.DEBUG)

    def initializations(self, dimension):
        # Important if you use the GAN
        grains_df = None
        self.setup_logging()
        if not self.gui_flag and not self.gan_flag:
            phase1 = self.root_dir + '/ExampleInput/ferrite_54_grains.csv'
            phase2 = self.root_dir + '/ExampleInput/pearlite_21_grains.csv'
        else:
            phase1 = self.file1
            phase2 = self.file2

        # Bei GAN-Input braucht man das nicht, weil der Input DIREKT über ein df kommt - therefore if not gan
        if not self.gan_flag:
            self.logger.info("RVE generation process has started...")
            phase1_a, phase1_b, phase1_c, phase1_alpha, phase1_phi1, phase1_PHI, phase1_phi2 = self.utils_obj.read_input(
                phase1, dimension)
            final_volume_phase1 = [(4 / 3 * phase1_a[i] * phase1_b[i] * phase1_c[i] * np.pi) for i in
                                   range(len(phase1_a))]
            phase1_a_shrinked = [phase1_a_i * self.shrink_factor for phase1_a_i in phase1_a]
            phase1_b_shrinked = [phase1_b_i * self.shrink_factor for phase1_b_i in phase1_b]
            phase1_c_shrinked = [phase1_c_i * self.shrink_factor for phase1_c_i in phase1_c]

            phase1_dict = {'a': phase1_a_shrinked,
                           'b': phase1_b_shrinked,
                           'c': phase1_c_shrinked,
                           'alpha': phase1_alpha,
                           'phi1': phase1_phi1,
                           'PHI': phase1_PHI,
                           'phi2': phase1_phi2,
                           'final_volume': final_volume_phase1}
            grains_df = pd.DataFrame(phase1_dict)
            grains_df['phaseID'] = 1

            if phase2 is not None:
                phase2_a, phase2_b, phase2_c, phase2_alpha, phase2_phi1, phase2_PHI, phase2_phi2 = self.utils_obj.read_input(
                    phase2, dimension)
                final_volume_phase2 = [(4 / 3 * phase2_a[i] * phase2_b[i] * phase2_c[i] * np.pi) for i in
                                       range(len(phase2_a))]
                phase2_a_shrinked = [phase2_a_i * self.shrink_factor for phase2_a_i in phase2_a]
                phase2_b_shrinked = [phase2_b_i * self.shrink_factor for phase2_b_i in phase2_b]
                phase2_c_shrinked = [phase2_c_i * self.shrink_factor for phase2_c_i in phase2_c]
                phase2_dict = {'a': phase2_a_shrinked,
                               'b': phase2_b_shrinked,
                               'c': phase2_c_shrinked,
                               'alpha': phase2_alpha,
                               'phi1': phase2_phi1,
                               'PHI': phase2_PHI,
                               'phi2': phase2_phi2,
                               'final_volume': final_volume_phase2}

                grains_phase2_df = pd.DataFrame(phase2_dict)
                grains_phase2_df['phaseID'] = 2
                grains_df = pd.concat([grains_df, grains_phase2_df])

            grains_df.sort_values(by='final_volume', inplace=True, ascending=False)
            grains_df.reset_index(inplace=True, drop=True)
            grains_df['GrainID'] = grains_df.index
            total_volume = sum(grains_df['final_volume'].values)
            estimated_boxsize = np.cbrt(total_volume)
            self.logger.info(
                "the total volume of your dataframe is {}. A boxsize of {} is recommended.".format(total_volume,
                                                                                                   estimated_boxsize))
        return grains_df  # Gibt hier einfach ein None zurück

    def rve_generation(self, epoch, grains_df):
        store_path = self.root_dir + '/OutputData/' + str(datetime.datetime.now())[:10] + '_' + str(epoch)
        if not os.path.isdir(store_path):
            os.makedirs(store_path)
        if not os.path.isdir(store_path + '/Figs'):
            os.makedirs(store_path + '/Figs')  # Second if needed

        """
        -------------------------------------------------------------------------------
        BAND-PHASE GENERATION HERE
        phaseID == 2 (Martensite)
        adjusted_size is: n_bands * bw * bs**2
        flag before the field
        -------------------------------------------------------------------------------
        """
        self.logger.info("RVE generation process has started with Band-creation")
        self.logger.info("The total volume of the RVE is {0}*{0}*{0} = {1}".format(self.box_size, self.box_size**3))
        adjusted_size = np.cbrt((self.number_of_bands * self.bandwidth * self.box_size ** 2)*self.band_filling)
        phase1 = self.sample_gan_input(size=800, labels=[3, 4, 5], adjusted_size=adjusted_size,
                                       maximum=self.bandwidth)
        bands_df = self.utils_obj.shrink_df(phase1, self.shrink_factor)
        bands_df['phaseID'] = 2
        self.logger.info('Sampled {} Martensite-Points for band-Creation!'.format(bands_df.__len__()))
        self.logger.info('The total volume is: {}'.format(np.sum(bands_df['final_volume'].values)))
        discrete_RSA_obj = DiscreteRsa3D(self.box_size, self.n_pts,
                                         bands_df['a'].tolist(),
                                         bands_df['b'].tolist(),
                                         bands_df['c'].tolist(),
                                         bands_df['alpha'].tolist(), store_path=store_path)

        # initialize empty grid_array for bands called band_array
        xyz = np.linspace(-self.box_size / 2, self.box_size + self.box_size / 2, 2 * self.n_pts, endpoint=True)
        x_grid, y_grid, z_grid = np.meshgrid(xyz, xyz, xyz)
        utils_obj_band = RVEUtils(self.box_size, self.n_pts,
                                  x_grid=x_grid, y_grid=y_grid, z_grid=z_grid, bandwidth=self.bandwidth)
        band_array = np.zeros((2 * self.n_pts, 2 * self.n_pts, 2 * self.n_pts))
        band_array = utils_obj_band.gen_boundaries_3D(band_array)

        for i in range(self.number_of_bands):
            band_array = utils_obj_band.band_generator(band_array)
        rsa, x_0_list, y_0_list, z_0_list, rsa_status = discrete_RSA_obj.run_rsa_clustered(banded_rsa_array=band_array,
                                                                                           animation=False)

        """
        ----------------------------------------------------------------------------------
        Placing the rest of the grains!
        Ferrite and Martensit Island
        adjusted_size is: bs**3 - n_bands * bw * bs**2 (Remaining Space)
        phases are 1 and 2, therefore sample two dfs
        Ratio is based on Martensite ratio in the steel grade
        ----------------------------------------------------------------------------------
        """
        if rsa_status:
            self.logger.info("RVE generation process continues with placing of the ferrite grains and martensite "
                             "islands")
            # Ferrite:
            adjusted_size_ferrite = np.cbrt((self.box_size ** 3 - self.number_of_bands * self.bandwidth *
                                            self.box_size ** 2) * self.phase_ratio)
            phase1 = self.sample_gan_input(size=800, labels=[0, 1, 2], adjusted_size=adjusted_size_ferrite)
            grains_df = self.utils_obj.shrink_df(phase1, self.shrink_factor)
            grains_df['phaseID'] = 1  # Ferrite_Grains
            self.logger.info('Sampled {} Ferrite-Points for the matrix!'.format(grains_df.__len__()))
            self.logger.info('The total volume is: {}'.format(np.sum(grains_df['final_volume'].values)))
            # Martensite
            adjusted_size_martensite = np.cbrt((self.box_size ** 3 - self.number_of_bands * self.bandwidth *
                                               self.box_size ** 2) * (1-self.phase_ratio))
            phase2 = self.sample_gan_input(size=800, labels=[3, 4, 5], adjusted_size=adjusted_size_martensite)
            grains_df_2 = self.utils_obj.shrink_df(phase2, self.shrink_factor)
            grains_df_2['phaseID'] = 2  # Martensite_Islands
            self.logger.info('Sampled {} Martensite-Islands for the matrix!'.format(grains_df_2.__len__()))
            self.logger.info('The total volume is: {}'.format(np.sum(grains_df_2['final_volume'].values)))

            # Sort again because of Concat
            grains_df = pd.concat([grains_df, grains_df_2])
            grains_df.sort_values(by='final_volume', inplace=True, ascending=False)
            grains_df.reset_index(inplace=True, drop=True)
            grains_df['GrainID'] = grains_df.index

            # Write out the grain data
            grains_df.to_csv(store_path + '/discrete_input_vol.csv', index=False)

            discrete_RSA_obj = DiscreteRsa3D(self.box_size, self.n_pts,
                                             grains_df['a'].tolist(),
                                             grains_df['b'].tolist(),
                                             grains_df['c'].tolist(),
                                             grains_df['alpha'].tolist(), store_path=store_path)

            # Run the 'rest' of the rsa:
            rsa, x_0_list, y_0_list, z_0_list, rsa_status = discrete_RSA_obj.run_rsa(band_ratio_rsa=1,
                                                                                     banded_rsa_array=rsa,
                                                                                     animation=self.animation,
                                                                                     x0_alt=x_0_list,
                                                                                     y0_alt=y_0_list,
                                                                                     z0_alt=z_0_list)
        else:
            self.logger.info("The normal rsa did not succeed...")
            sys.exit()

        """
        ---------------------------------------------------------------------
        RUN THE TESSELATION
        Tesselation is based on both of the RSA's, the normal and the clustered one. To run the tesselation, the band 
        and the "normal"-df's have to be concated to run a sufficient generation
        ---------------------------------------------------------------------
        """
        if rsa_status:
            self.logger.info("RVE generation process continues with the tesselation of grains!")
            # Passe Grain-IDs an
            rsa = self.utils_obj.rearange_grain_ids_bands(bands_df=bands_df,
                                                          grains_df=grains_df,
                                                          rsa=rsa)
            # Concat all the data
            whole_df = pd.concat([grains_df, bands_df])
            whole_df.reset_index(inplace=True, drop=True)
            whole_df['GrainID'] = whole_df.index
            discrete_tesselation_obj = Tesselation3D(self.box_size, self.n_pts,
                                                     whole_df['a'].tolist(),
                                                     whole_df['b'].tolist(),
                                                     whole_df['c'].tolist(),
                                                     whole_df['alpha'].tolist(),
                                                     x_0_list, y_0_list, z_0_list,
                                                     whole_df['final_volume'].tolist(),
                                                     self.shrink_factor, 1, store_path)

            rve, rve_status = discrete_tesselation_obj.run_tesselation(rsa, animation=self.animation)
            # Change the band_ids to -200
            for i in range(len(grains_df), len(whole_df)):
                rve[np.where(rve == i + 1)] = -200

        else:
            self.logger.info("The tesselation did not succeed...")
            sys.exit()

        """
        -------------------------------------------------------------------------
        PLACE THE INCLUSIONS!
        The inclusions will not grow and are therefore placed in the rve AFTER the
        Tesselation! The inclusions will placed inside another grain and cannot cut a 
        grain boundary. Labels are lower -200
        -------------------------------------------------------------------------
        """
        if rve_status and self.inclusions_flag:
            self.logger.info("RVE generation process reaches final steps: Placing inclusions in the matrix")
            adjusted_size = self.box_size * np.cbrt(self.inclusion_ratio)  # 1% as an example
            inclusions = self.sample_gan_input(size=200, labels=(3, 4, 5), adjusted_size=adjusted_size)
            # Processing mit shrinken - Das könnte mal in eine Funktion :)
            inclusions_df = self.utils_obj.shrink_df(inclusions, self.shrink_factor)
            inclusions_df['phaseID'] = 2  # Inclusions also elastic
            self.logger.info('Sampled {} inclusions for the RVE'.format(inclusions_df.__len__()))
            self.logger.info('The total volume is: {}'.format(np.sum(inclusions_df['final_volume'].values)))

            discrete_RSA_inc_obj = DiscreteRsa3D(self.box_size, self.n_pts,
                                                 inclusions_df['a'].tolist(),
                                                 inclusions_df['b'].tolist(),
                                                 inclusions_df['c'].tolist(),
                                                 inclusions_df['alpha'].tolist(), store_path=store_path)

            rve, rve_status = discrete_RSA_inc_obj.run_rsa_inclusions(rve, animation=True)
            print(np.asarray(np.unique(rve, return_counts=True)).T)
            print(grains_df)

        if rve_status:
            self.logger.info("RVE generation process nearly complete: Creating Abaqus input now:")
            periodic_rve_df = self.utils_obj.repair_periodicity_3D(rve)
            periodic_rve_df['phaseID'] = 0
            grains_df.sort_values(by=['GrainID'])
            print(grains_df)

            for i in range(len(grains_df)):
                # Set grain-ID to number of the grain
                # Denn Grain-ID ist entweder >0 oder -200 oder >-200
                periodic_rve_df.loc[periodic_rve_df['GrainID'] == i + 1, 'phaseID'] = grains_df['phaseID'][i]

            # For the inclusions:
            if self.inclusions_flag:
                # Zuweisung der negativen grain-ID's
                for j in range(len(inclusions_df)):
                    periodic_rve_df.loc[periodic_rve_df['GrainID'] == -(200 + j + 1), 'GrainID'] = (i + j + 2)
                    periodic_rve_df.loc[periodic_rve_df['GrainID'] == (i + j + 2), 'phaseID'] = 2

            print(periodic_rve_df)
            print(periodic_rve_df['GrainID'].value_counts())

            if self.number_of_bands > 0 and self.inclusions_flag:
                # Set the points where == -200 to phase 2 and to grain ID i + j + 3
                periodic_rve_df.loc[periodic_rve_df['GrainID'] == -200, 'GrainID'] = (i + j + 3)
                periodic_rve_df.loc[periodic_rve_df['GrainID'] == (i + j + 3), 'phaseID'] = 2
            else:
                # Set the points where == -200 to phase 2 and to grain ID i + 2
                periodic_rve_df.loc[periodic_rve_df['GrainID'] == -200, 'GrainID'] = (i + 2)
                periodic_rve_df.loc[periodic_rve_df['GrainID'] == (i + 2), 'phaseID'] = 2


            # Start the Mesher
            mesher_obj = Mesher(periodic_rve_df, store_path=store_path, phase_two_isotropic=True, animation=False,
                                tex_phi1=grains_df['phi1'].tolist(), tex_PHI=grains_df['PHI'].tolist(),
                                tex_phi2=grains_df['phi2'].tolist())
            mesher_obj.mesh_and_build_abaqus_model()

        self.logger.info("RVE generation process has successfully completed...")