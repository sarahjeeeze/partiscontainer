#!/usr/bin/env python
import sys
import os
import re
import random
import numpy
import math
import tempfile
import json
from subprocess import check_call

from hist import Hist
import utils
import treeutils

# ----------------------------------------------------------------------------------------
class TreeGenerator(object):
    def __init__(self, args, parameter_dir):
        self.args = args
        self.parameter_dir = parameter_dir
        self.set_branch_lengths()  # for each region (and 'all'), a list of branch lengths and a list of corresponding probabilities (i.e. two lists: bin centers and bin contents). Also, the mean of the hist.
        self.n_trees_each_run = '1'  # it would no doubt be faster to have this bigger than 1, but this makes it easier to vary the n-leaf distribution

    #----------------------------------------------------------------------------------------
    def convert_observed_changes_to_branch_length(self, mute_freq):
        if not self.args.no_per_base_mutation:  # in this case we set the per-base freq (equilibrium freq) for the germline base to zero, so don't need to account for this
            return mute_freq
        # for consistency with the rest of the code base, we call it <mute_freq> instead of "fraction of observed changes"
        # JC69 formula, from wikipedia
        # NOTE this helps, but is not sufficient, because the mutation rate is super dominated by a relative few very highly mutated positions
        argument = max(1e-2, 1. - (4./3)* mute_freq)  # HACK arbitrarily cut it off at 0.01 (only affects the very small fraction with mute_freq higher than about 0.75)
        return -(3./4) * math.log(argument)

    #----------------------------------------------------------------------------------------
    def get_mute_hist(self, mtype):
        if self.args.mutate_from_scratch:
            mean_mute_val = self.args.scratch_mute_freq
            if self.args.same_mute_freq_for_all_seqs:
                hist = Hist(1, mean_mute_val - utils.eps, mean_mute_val + utils.eps)
                hist.fill(mean_mute_val)
            else:
                n_entries = 500
                length_vals = [v for v in numpy.random.exponential(mean_mute_val, n_entries)]  # count doesn't work on numpy.ndarray objects
                max_val = 0.8  # this is arbitrary, but you shouldn't be calling this with anything that gets a significant number anywhere near there, anyway
                if length_vals.count(max_val):
                    print '%s lots of really high mutation rates treegenerator::get_mute_hist()' % utils.color('yellow', 'warning')
                length_vals = [min(v, max_val) for v in length_vals]
                hist = Hist(30, 0., max_val)
                for val in length_vals:
                    hist.fill(val)
                hist.normalize()
        else:
            hist = Hist(fname=self.parameter_dir + '/' + mtype + '-mean-mute-freqs.csv')

        return hist

    #----------------------------------------------------------------------------------------
    def set_branch_lengths(self):
        self.branch_lengths = {}
        for mtype in ['all'] + utils.regions:
            hist = self.get_mute_hist(mtype)
            hist.normalize(include_overflows=False, expect_overflows=True)  # if it was written with overflows included, it'll need to be renormalized
            lengths, probs = [], []
            for ibin in range(1, hist.n_bins + 1):  # ignore under/overflow bins
                freq = hist.get_bin_centers()[ibin]
                lengths.append(self.convert_observed_changes_to_branch_length(float(freq)))
                probs.append(hist.bin_contents[ibin])
            self.branch_lengths[mtype] = {'mean' : hist.get_mean(), 'lengths' : lengths, 'probs' : probs}

            if not utils.is_normed(probs):
                raise Exception('not normalized %f' % check_sum)

    #----------------------------------------------------------------------------------------
    def choose_full_sequence_branch_length(self):
        iprob = numpy.random.uniform(0,1)
        sum_prob = 0.0
        for ibin in range(len(self.branch_lengths['all']['lengths'])):
            sum_prob += self.branch_lengths['all']['probs'][ibin]
            if iprob < sum_prob:
                return self.branch_lengths['all']['lengths'][ibin]
                
        assert False  # shouldn't fall through to here
    
    # ----------------------------------------------------------------------------------------
    def choose_n_leaves(self):
        if self.args.constant_number_of_leaves:
            return self.args.n_leaves

        if self.args.n_leaf_distribution == 'geometric':
            return numpy.random.geometric(1./self.args.n_leaves)
        elif self.args.n_leaf_distribution == 'box':
            width = self.args.n_leaves / 5.  # whatever
            lo, hi = int(self.args.n_leaves - width), int(self.args.n_leaves + width)
            if hi - lo <= 0:
                raise Exception('n leaves %d and width %f round to bad box bounds [%f, %f]' % (self.args.n_leaves, width, lo, hi))
            return random.randint(lo, hi)  # NOTE interval is inclusive!
        elif self.args.n_leaf_distribution == 'zipf':
            return numpy.random.zipf(self.args.n_leaves)  # NOTE <n_leaves> is not the mean here
        else:
            raise Exception('n leaf distribution %s not among allowed choices' % self.args.n_leaf_distribution)

    # ----------------------------------------------------------------------------------------
    def run_treesim(self, seed, outfname, workdir):
        if self.args.debug or utils.getsuffix(outfname) == '.nwk':
            print '  generating %d trees,' % self.args.n_trees,
            if self.args.constant_number_of_leaves:
                print 'all with %s leaves' % str(self.args.n_leaves)
            else:
                print 'n-leaves from %s distribution with parameter %s' % (self.args.n_leaf_distribution, str(self.args.n_leaves))
            if self.args.debug:
                print '        mean branch lengths from %s' % (self.parameter_dir if self.parameter_dir is not None else 'scratch')
                for mtype in ['all',] + utils.regions:
                    print '         %4s %7.3f (ratio %7.3f)' % (mtype, self.branch_lengths[mtype]['mean'], self.branch_lengths[mtype]['mean'] / self.branch_lengths['all']['mean'])

        ages, treestrs = [], []

        cmd_lines = []
        pkgname = 'TreeSim'  # TreeSimGM when root_mrca_weibull_parameter is set, otherwise TreeSim
        if self.args.root_mrca_weibull_parameter is not None:
            pkgname += 'GM'
        cmd_lines += ['require(%s, quietly=TRUE)' % pkgname]
        cmd_lines += ['set.seed(' + str(seed)+ ')']
        for itree in range(self.args.n_trees):
            n_leaves = self.choose_n_leaves()
            age = self.choose_full_sequence_branch_length()
            ages.append(age)
            if n_leaves == 1:  # add singleton trees by hand
                treestrs.append('t1:%f;' % age)
                continue
            treestrs.append(None)

            # NOTE these simulation functions seem to assume that we want all the extant leaves to have the same height. Which is kind of weird. Maybe makes more sense at some point to change this.
            params = {'n' : n_leaves, 'numbsim' : self.n_trees_each_run}
            if self.args.root_mrca_weibull_parameter is None:
                fcn = 'sim.bd.taxa.age'
                params['lambda'] = 1  # speciation_rate
                params['mu'] = 0.5  # extinction_rate
                params['age'] = age
            else:
                fcn = 'sim.taxa'
                params['distributionspname'] = '"rweibull"'
                params['distributionspparameters'] = 'c(%f, 1)' % self.args.root_mrca_weibull_parameter
                params['labellivingsp'] = '"t"'  # TreeSim doesn't let you do this, but a.t.m. this is their default
            cmd_lines += ['trees <- %s(%s)' % (fcn, ', '.join(['%s=%s' % (k, str(v)) for k, v in params.items()]))]
            cmd_lines += ['write.tree(trees[[1]], \"' + outfname + '\", append=TRUE)']

        if None not in treestrs:  # if every tree has one leaf, we don't need to run R
            open(outfname, 'w').close()
        else:
            if os.path.exists(outfname):
                os.remove(outfname)
            utils.run_r(cmd_lines, workdir)

        with open(outfname) as treefile:
            for itree, tstr in enumerate(treestrs):
                if tstr is None:
                    treestrs[itree] = treefile.readline().strip()
            if None in treestrs:
                raise Exception('didn\'t read enough trees from %s: still %d empty places in treestrs' % (outfname, treestrs.count(None)))

        # rescale branch lengths (TreeSim lets you specify the number of leaves and the height at the same time, but TreeSimGM doesn't, and TreeSim's numbers are usually a little off anyway... so we rescale everybody)
        for itree in range(len(ages)):
            treestrs[itree] = '(%s):0.0;' % treestrs[itree].rstrip(';')  # the trees it spits out have non-zero branch length above root (or at least that's what the newick strings turn into when dendropy reads them), which is fucked up and annoying, so here we add a new/real root at the top of the original root's branch
            treestrs[itree] = treeutils.rescale_tree(ages[itree], treestr=treestrs[itree])

        return ages, treestrs

    # ----------------------------------------------------------------------------------------
    def read_input_tree_file(self, outfname):
        if self.args.debug:
            print '  reading trees from %s' % self.args.input_simulation_treefname
        utils.simplerun('cp %s %s' % (self.args.input_simulation_treefname, outfname), debug=False)
        ages, treestrs = [], []
        with open(outfname) as treefile:
            for line in treefile:
                tstr = line.strip()
                if tstr == '':  # skip empty lines
                    continue
                dtree = treeutils.get_dendro_tree(treestr=tstr, suppress_internal_node_taxa=True)
                if dtree.seed_node.edge_length is None:  # make sure root edge length is set (otherwise bppseqgen barfs)
                    dtree.seed_node.edge_length = 0.
                old_new_label_pairs = [(l.taxon.label, 't%d' % (i+1)) for i, l in enumerate(dtree.leaf_node_iter())]
                treeutils.translate_labels(dtree, old_new_label_pairs)  # rename the leaves to t1, t2, etc. (it would be nice to not have to do this, but a bunch of stuff in recombinator uses this  to check that e.g. bppseqgen didn't screw up the ordering)
                age = self.choose_full_sequence_branch_length()
                if self.args.debug > 1:  # it's easier to keep this debug line separate up here than make a tmp variable to keep track of the old height
                    print '    input tree %d (rescaled depth %.3f --> %.3f):' % (len(ages), treeutils.get_mean_leaf_height(tree=dtree), age)
                treeutils.rescale_tree(age, dtree=dtree)  # I think this gets rescaled again for each event, so we could probably in principle avoid this rescaling, but if the input depth is greater than one stuff starts breaking, so may as well do it now
                ages.append(age)
                treestrs.append(dtree.as_string(schema='newick').strip())
                if self.args.debug > 1:
                    print utils.pad_lines(treeutils.get_ascii_tree(dtree))
        if any(a > 1. for a in ages):
            raise Exception('tree depths must be less than 1., but trees read from %s don\'t satisfy this: %s' % (self.args.input_simulation_treefname, ages))
        if len(ages) != self.args.n_trees:
            print '    resetting --n-trees from %d to %d to match trees read from %s' % (self.args.n_trees, len(ages), self.args.input_simulation_treefname)
        self.args.n_trees = len(ages)

        return ages, treestrs

    # ----------------------------------------------------------------------------------------
    def generate_trees(self, seed, outfname, workdir):
        if self.args.input_simulation_treefname is None:  # default: generate our own trees
            ages, treestrs = self.run_treesim(seed, outfname, workdir)
        else:  # read trees from a file that pass set on the command line
            ages, treestrs = self.read_input_tree_file(outfname)
        os.remove(outfname)  # remove it here, just to make clear that we *re*write it in self.post_process_trees() so that recombinator can later read it

        if self.args.debug or utils.getsuffix(outfname) == '.nwk':
            dtreelist = [treeutils.get_dendro_tree(treestr=tstr, suppress_internal_node_taxa=True) for tstr in treestrs]
            mean_leaf_height_list = [treeutils.get_mean_leaf_height(tree=dt) for dt in dtreelist]
            n_leaf_list = [treeutils.get_n_leaves(dt) for dt in dtreelist]
            print '    mean over %d trees:   depth %.5f   leaves %.2f' % (len(mean_leaf_height_list), numpy.mean(mean_leaf_height_list), numpy.mean(n_leaf_list))

        # each tree is written with branch length the mean branch length over the whole sequence (which is different for each tree), but recombinator also needs the relative length for each region (which is the same, it's an average over the whole repertoire)
        with open(outfname, 'w') as yfile:
            if utils.getsuffix(outfname) == '.yaml':
                yamlfo = {'branch-length-ratios' : {r : self.branch_lengths[r]['mean'] / self.branch_lengths['all']['mean'] for r in utils.regions},
                          'trees' : treestrs}
                json.dump(yamlfo, yfile)
            elif utils.getsuffix(outfname) == '.nwk':
                print '    writing trees to %s' % outfname
                for treestr in treestrs:
                    yfile.write(treestr + '\n')
            else:
                assert False
