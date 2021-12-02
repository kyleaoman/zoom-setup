"""
Convert ICs produced by IC_Gen into a single file in SWIFT format.

"""

import numpy as np
import argparse
import h5py as h5
import os

from pdb import set_trace

def main():
    args = parse_arguments()
    swiftICs = SwiftICs(args)
    swiftICs.isolate_gas(args)
    swiftICs.remap_ids(args)
    swiftICs.save(args)

class SwiftICs:
    """
    Generate and store the ICs for SWIFT.
    """
    def __init__(self, args):
        in_file = args.input_file_name
        if not os.path.isfile(in_file):
            raise OSError(f"Specified input file '{in_file}' not found!")
        self.header = self.load_header(in_file)
        self.meta = self.load_meta_data(args)
        num_input_files = self.header['NumFilesPerSnapshot']
        self.num_parts = self.header['NumPart_Total']

        self.pt1 = self.load_parts(in_file, num_input_files, 1)
        self.pt2 = self.load_parts(in_file, num_input_files, 2)

    def load_header(self, in_file):
        """Parse the header from the specified input file into a dict."""
        header = {}
        with h5.File(in_file, 'r') as f:
            g = f['Header']
            for key in g.attrs.keys():
                if key in ['BoxSize', 'Flag_Entropy_ICs', 'MassTable',
                           'NumFilesPerSnapshot', 'NumPart_Total',
                           'NumPart_Total_HighWord','Time', 'HubbleParam']:
                    header[key] = g.attrs[key]

        header['BoxSize'] /= header['HubbleParam']

        return header

    def load_parts(self, in_file, num_files, ptype):
        """Load all data for a specific particle type."""
        props = ['Coordinates', 'Masses', 'ParticleIDs', 'Velocities']
        parts = {}
        offset = 0        
        name_parts = in_file.split('.')

        for ifile in range(num_files):
            name_parts[-2] = f'{ifile}'
            this_file = '.'.join(name_parts)

            with h5.File(this_file, 'r') as f:
                num_this_file = f['Header'].attrs['NumPart_ThisFile'][ptype]
                if num_this_file == 0:
                    print(f"No particles of type {ptype} on file {ifile}...")
                    continue
    
                out_loc = np.s_[offset : offset+num_this_file, ...]
                print(f"Filling particles {offset} : {offset+num_this_file}")
                offset += num_this_file
                g = f[f'PartType{ptype}']
                for prop in props:
                    if prop not in parts:
                        dims = list(g[prop].shape)
                        dims[0] = self.num_parts[ptype]
                        parts[prop] = np.zeros(dims, dtype=g[prop].dtype)-1
                    g[prop].read_direct(parts[prop], None, out_loc)

        if self.header['MassTable'][ptype] > 0:
            parts['Masses'] = (
                np.zeros(self.num_parts[ptype], dtype="float32")
                + self.header['MassTable'][ptype]
            )
        if 'Masses' in parts:
            parts['Masses'] /= self.header['HubbleParam']
        if 'Coordinates' in parts:
            parts['Coordinates'] /= self.header['HubbleParam']
        return parts

    def load_meta_data(self, args):
        pl_meta_file = args.pl_meta_file
        meta = {}
        with h5.File(pl_meta_file, 'r') as f:
            h = f['Header']
            meta['OmegaDM'] = h.attrs['OmegaDM']
            meta['OmegaLambda'] = h.attrs['OmegaLambda']
            meta['OmegaBaryon'] = h.attrs['OmegaBaryon']
            meta['N_Part_Equiv'] = h.attrs['N_Part_Equiv']

        return meta

    def isolate_gas(self, args):
        """Isolate gas particles, if desired."""
        if not args.isolate_gas:
            return

        h = self.header['HubbleParam']
        pt1 = self.pt1

        pl_meta_file = args.pl_meta_file
        with h5.File(pl_meta_file, 'r') as f:
            mgas = f['ZoneI'].attrs['m_gas_msun'] / 1e10
            mdm = f['ZoneI'].attrs['m_dm_msun'] / 1e10
            mips = f['ZoneI'].attrs['MeanInterParticleSeparation_gas_Mpc']

        ind_gas = np.nonzero(
            np.abs(pt1['Masses'] - mgas) / mgas < 1e-4)[0]
        ind_dm = np.nonzero(
            np.abs(pt1['Masses'] - mdm) / mdm < 1e-4)[0]

        n_gas = len(ind_gas)
        n_dm = len(ind_dm)

        if n_gas + n_dm != self.num_parts[1]:
            raise ValueError(
                f"Have {self.num_parts[1]} Type1 particles in ICs, but "
                f"{n_dm} identified as DM and {n_gas} as gas..."
            )

        pt0 = {}
        for key in pt1:
            pt0[key] = pt1[key][ind_gas]
            pt1[key] = pt1[key][ind_dm]
        self.num_parts[0] = n_gas
        self.num_parts[1] = n_dm

        # Generate smoothing lengths for gas.
        pt0['InternalEnergy'] = np.zeros(n_gas)
        pt0['SmoothingLength'] = np.zeros(n_gas) + mips

        self.pt0 = pt0

    def remap_ids(self, args):
        pass

    def save(self, args):
        """Write the data to a SWIFT-compatible single file."""

        out_file = args.output_file_name
        if out_file is None:
            out_file = args.input_file_name
            out_file_parts = out_file.split('.')
            out_file = '.'.join(out_file_parts[:-2]) + '.hdf5'

        print(f"Writing output to {out_file}...")

        with h5.File(out_file, 'w') as f:

            # Header. MUST CHECK WHETHER NAMES MUST BE CHANGED!
            self.header['NumFilesPerSnapshot'] = 1
            self.header['NumPart_ThisFile'] = self.num_parts
            self.header['NumPart_Total'] = self.num_parts

            h = f.create_group('Header')
            for key in self.header:
                h.attrs[key] = self.header[key]

            if self.num_parts[0] > 0:
                pt0 = f.create_group('PartType0')
                for key in self.pt0:
                    pt0[key] = self.pt0[key]

            pt1 = f.create_group('PartType1')
            for key in self.pt1:
                pt1[key] = self.pt1[key]

            if self.num_parts[2] > 0:
                pt2 = f.create_group('PartType2')
                for key in self.pt2:
                    pt2[key] = self.pt2[key]

            # Bake in metadata for simulation setup
            m = f.create_group('Metadata')
            for key in self.meta:
                m.attrs[key] = self.meta[key]

def parse_arguments():
    """Parse the command-line arguments."""

    parser = argparse.ArgumentParser(
        description="Convert partial ICs files from IC_Gen "
                    "into a single SWIFT compatible file."
    )
    parser.add_argument(
        'workdir', help='Working directory for the IC generation.')

    parser.add_argument(
        '-f', '--input_file_name',
        help="The name of one of the IC files from IC_Gen."
    )
    parser.add_argument(
        '-o', '--output_file_name',
        help="The output file to contain the SWIFT-compatible ICs."
    )
    parser.add_argument(
        '-g', '--isolate_gas', action='store_true',
        help="Isolate gas particles in ICs?")
    parser.add_argument(
        '-m', '--pl_meta_file', default=None,
        help="Particle load metadata file, to isolate gas particles. "
             "By default, this is `particle_load_info.hdf5' in workdir."
    )

    args = parser.parse_args()

    if args.input_file_name is None:
        sim_name = args.workdir.split('/')[-1]
        args.input_file_name = args.workdir + '/ICs/' + sim_name + '.0.hdf5'
    if args.pl_meta_file is None:
        args.pl_meta_file = args.workdir + "/particle_load_info.hdf5"
        
    # Some sanity checks
    if not os.path.isfile(args.pl_meta_file):
        raise OSError("Could not find PL metadata file {args.pl_meta_file}!")
    if not os.path.isfile(args.input_file_name):
        raise OSError("Could not find input ICs file {args.input_file_name}!")

    return args


if __name__ == '__main__':
    main()
