#!/usr/bin/env python
import argparse
import csv
import colored_traceback.always
import collections
import copy
import os
import sys
import numpy
import math
import time
import traceback

current_script_dir = os.path.dirname(os.path.realpath(__file__)).replace('/bin', '/python')
sys.path.insert(1, current_script_dir)
import utils
import indelutils
import treeutils
from event import RecombinationEvent

ete_path = '/home/' + os.getenv('USER') + '/anaconda_ete/bin'
bcr_phylo_path = os.getenv('PWD') + '/packages/bcr-phylo-benchmark'

# ----------------------------------------------------------------------------------------
def simdir():
    return '%s/%s/simu' % (args.base_outdir, args.stype)
def infdir():
    return '%s/%s/partis' % (args.base_outdir, args.stype)
def naive_fname():
    return '%s/naive-simu.yaml' % simdir()
def bcr_phylo_fasta_fname(outdir):
    return '%s/%s.fasta' % (outdir, args.extrastr)
def simfname():
    return '%s/mutated-simu.yaml' % simdir()
def param_dir():
    return '%s/params' % infdir()
def partition_fname():
    return '%s/partition.yaml' % infdir()

# ----------------------------------------------------------------------------------------
def rearrange():
    if utils.output_exists(args, naive_fname(), outlabel='naive simu', offset=4):
        return
    cmd = './bin/partis simulate --simulate-from-scratch --mutation-multiplier 0.0001 --n-leaves 1 --constant-number-of-leaves'  # tends to get in infinite loop if you actually pass 0. (yes, I should fix this)
    cmd += ' --debug %d --seed %d --outfname %s --n-sim-events %d' % (int(args.debug), args.seed, naive_fname(), args.n_sim_events)
    if args.restrict_available_genes:
        cmd += ' --only-genes IGHV1-18*01:IGHJ1*01'
    if args.n_procs > 1:
        cmd += ' --n-procs %d' % args.n_procs
    if args.slurm:
        cmd += ' --batch-system slurm'
    utils.simplerun(cmd, debug=True)

# ----------------------------------------------------------------------------------------
def get_vpar_val(parg, pval, debug=False):  # get value of parameter/command line arg that is allowed to (but may not at the moment) be drawn from a variable distribution (note we have to pass in <pval> for args that are lists)
    if args.parameter_variances is None or parg not in args.parameter_variances:  # default: just use the single, fixed value from the command line
        return pval
    def sfcn(x):  # just for dbg/exceptions
        return str(int(x)) if parg != 'selection-strength' else ('%.2f' % x)
    pvar = args.parameter_variances[parg]
    if '..' in pvar:  # list of allowed values NOTE pval is *not* used if we're choosing from several choices (ick, but not sure what else to do)
        dbgstr = '[%s]' % pvar.replace('..', ', ')
        return_val = numpy.random.choice([float(pv) for pv in pvar.split('..')])
    else:  # actual parameter variance (i know, this is ugly)
        parg_bounds = {'min' : {'n-sim-seqs-per-generation' : 1}, 'max' : {}}
        pmean = pval
        pvar = float(pvar)
        pmin, pmax = pmean - 0.5 * pvar, pmean + 0.5 * pvar
        if pmin < 0:
            raise Exception('min parameter value for %s less than 0 (from mean %s and half width %s)' % (parg, sfcn(pmean), sfcn(pvar)))
        if parg == 'selection-strength' and pmax > 1:
            raise Exception('max parameter value for %s greater than 1 (from mean %s and half width %s)' % (parg, sfcn(pmean), sfcn(pvar)))
        if parg in parg_bounds['min'] and pmin < parg_bounds['min'][parg]:
            raise Exception('min value too small for %s: %f < %f' % (parg, pmin, parg_bounds['min'][parg]))
        if parg in parg_bounds['max'] and pmax > parg_bounds['max'][parg]:
            raise Exception('max value too large for %s: %f > %f' % (parg, pmax, parg_bounds['max'][parg]))
        dbgstr = '[%6s, %6s]' % (sfcn(pmin), sfcn(pmax))
        return_val = numpy.random.uniform(pmin, pmax)
    if parg != 'selection-strength':
        return_val = int(return_val)
    if debug:
        print '  %30s --> %-7s  %s' % (dbgstr, sfcn(return_val), parg)
    return return_val

# ----------------------------------------------------------------------------------------
def run_bcr_phylo(naive_line, outdir, ievent, n_total_events, uid_str_len=None):
    if utils.output_exists(args, bcr_phylo_fasta_fname(outdir), outlabel='bcr-phylo', offset=4):
        return None

    cmd = '%s/bin/simulator.py' % bcr_phylo_path
    if args.run_help:
        cmd += ' --help'
    elif args.stype == 'neutral':
        assert False  # needs updating (well, maybe not, but I'm not thinking about it when I move the selection parameters to command line args)
        cmd += ' --lambda %f --lambda0 %f' % (1.5, 0.365)
        cmd += ' --n_final_seqs %d' % args.n_sim_seqs_per_generation
    elif args.stype == 'selection':
        cmd += ' --selection'
        cmd += ' --lambda %f' % args.branching_parameter
        cmd += ' --lambda0 %f' % args.base_mutation_rate
        cmd += ' --selection_strength %f' % get_vpar_val('selection-strength', args.selection_strength)
        cmd += ' --obs_times %s' % ' '.join(['%d' % get_vpar_val('obs-times', t) for t in args.obs_times])
        cmd += ' --n_to_sample %s' % ' '.join('%d' % get_vpar_val('n-sim-seqs-per-generation', n) for n in args.n_sim_seqs_per_generation)
        cmd += ' --metric_for_target_dist %s' % args.metric_for_target_distance
        if args.paratope_positions is not None:
            cmd += ' --paratope_positions %s' % args.paratope_positions
        cmd += ' --target_dist %d' % args.target_distance
        cmd += ' --target_count %d' % args.target_count
        cmd += ' --carry_cap %d' % get_vpar_val('carry-cap', args.carry_cap)
        if not args.dont_observe_common_ancestors:
            cmd += ' --observe_common_ancestors'
        if args.leaf_sampling_scheme is not None:
            cmd += ' --leaf_sampling_scheme %s' % args.leaf_sampling_scheme
        if args.n_target_clusters is not None:
            cmd += ' --n_target_clusters %d' % args.n_target_clusters
        # cmd += ' --target_cluster_distance 1'
        if args.min_target_distance is not None:
            cmd += ' --min_target_distance %d' % args.min_target_distance
    else:
        assert False

    cmd += ' --debug %d' % args.debug
    cmd += ' --n_tries 1000'
    if args.context_depend == 0:
        cmd += ' --no_context'
    cmd += ' --no_plot'
    if args.only_csv_plots:
        cmd += ' --dont_write_hists'
    cmd += ' --outbase %s/%s' % (outdir, args.extrastr)
    cmd += ' --random_seed %d' % (args.seed + ievent)
    if uid_str_len is not None:
        cmd += ' --uid_str_len %d' % uid_str_len
    cmd += ' --naive_seq %s' % naive_line['naive_seq']

    if not os.path.exists(outdir):
        os.makedirs(outdir)

    cfo = None
    if args.n_procs == 1:
        utils.run_ete_script(cmd, ete_path)  # NOTE kind of hard to add a --dry-run option, since we have to loop over the events we made in rearrange()
    else:
        cmd, _ = utils.run_ete_script(cmd, ete_path, return_for_cmdfos=True, tmpdir=outdir)
        cfo = {'cmd_str' : cmd, 'workdir' : outdir, 'outfname' : bcr_phylo_fasta_fname(outdir)}
    return cfo

# ----------------------------------------------------------------------------------------
def parse_bcr_phylo_output(glfo, naive_line, outdir, ievent):
    seqfos = utils.read_fastx(bcr_phylo_fasta_fname(outdir))  # output mutated sequences from bcr-phylo

    assert len(naive_line['unique_ids']) == 1  # enforces that we ran naive-only, 1-leaf partis simulation above
    assert not indelutils.has_indels(naive_line['indelfos'][0])  # would have to handle this below
    if args.debug:
        utils.print_reco_event(naive_line)
    reco_info = collections.OrderedDict()
    for sfo in seqfos:
        mline = copy.deepcopy(naive_line)
        utils.remove_all_implicit_info(mline)
        del mline['tree']
        mline['unique_ids'] = [sfo['name']]
        mline['seqs'] = [sfo['seq']]  # it's really important to set both the seqs (since they're both already in there from the naive line)
        mline['input_seqs'] = [sfo['seq']]  # it's really important to set both the seqs (since they're both already in there from the naive line)
        mline['duplicates'] = [[]]
        reco_info[sfo['name']] = mline
        try:
            utils.add_implicit_info(glfo, mline)
        except:  # TODO not sure if I really want to leave this in long term, but it shouldn't hurt anything (it's crashing on unequal naive/mature sequence lengths, and I need this to track down which event it is) UPDATE: yeah it was just because something crashed in the middle of writing a .fa file
            print 'implicit info adding failed for ievent %d in %s' % (ievent, outdir)
            lines = traceback.format_exception(*sys.exc_info())
            print utils.pad_lines(''.join(lines))  # NOTE this will still crash on the next line if implicit info adding failed
    final_line = utils.synthesize_multi_seq_line_from_reco_info([sfo['name'] for sfo in seqfos], reco_info)
    if args.debug:
        utils.print_reco_event(final_line)

    # extract kd values from pickle file (use a separate script since it requires ete/anaconda to read)
    if args.stype == 'selection':
        kdfname, nwkfname = '%s/kd-vals.csv' % outdir, '%s/simu.nwk' % outdir
        if not utils.output_exists(args, kdfname, outlabel='kd/nwk conversion', offset=4):  # eh, don't really need to check for both kd an nwk file, chances of only one being missing are really small, and it'll just crash when it looks for it a couple lines later
            cmd = './bin/read-bcr-phylo-trees.py --pickle-tree-file %s/%s_lineage_tree.p --kdfile %s --newick-tree-file %s' % (outdir, args.extrastr, kdfname, nwkfname)
            utils.run_ete_script(cmd, ete_path, debug=args.n_procs==1)
        nodefo = {}
        with open(kdfname) as kdfile:
            reader = csv.DictReader(kdfile)
            for line in reader:
                nodefo[line['uid']] = {
                    'kd' : float(line['kd']),
                    'relative_kd' : float(line['relative_kd']),
                    'lambda' : line.get('lambda', None),
                    'target_index' : int(line['target_index']),
                }
        if len(set(nodefo) - set(final_line['unique_ids'])) > 0:  # uids in the kd file but not the <line> (i.e. not in the newick/fasta files) are probably just bcr-phylo discarding internal nodes
            print '        in kd file, but missing from final_line (probably just internal nodes that bcr-phylo wrote to the tree without names): %s' % (set(nodefo) - set(final_line['unique_ids']))
        if len(set(final_line['unique_ids']) - set(nodefo)) > 0:
            print '        in final_line, but missing from kdvals: %s' % ' '.join(set(final_line['unique_ids']) - set(nodefo))
        final_line['affinities'] = [1. / nodefo[u]['kd'] for u in final_line['unique_ids']]
        final_line['relative_affinities'] = [1. / nodefo[u]['relative_kd'] for u in final_line['unique_ids']]
        final_line['lambdas'] = [nodefo[u]['lambda'] for u in final_line['unique_ids']]
        final_line['nearest_target_indices'] = [nodefo[u]['target_index'] for u in final_line['unique_ids']]
        tree = treeutils.get_dendro_tree(treefname=nwkfname)
        tree.scale_edges(1. / numpy.mean([len(s) for s in final_line['seqs']]))
        if args.debug:
            print utils.pad_lines(treeutils.get_ascii_tree(dendro_tree=tree), padwidth=12)
        final_line['tree'] = tree.as_string(schema='newick')
    tmp_event = RecombinationEvent(glfo)  # I don't want to move the function out of event.py right now
    tmp_event.set_reco_id(final_line, irandom=ievent)  # not sure that setting <irandom> here actually does anything

    # get target sequences
    target_seqfos = utils.read_fastx('%s/%s_targets.fa' % (outdir, args.extrastr))
    final_line['target_seqs'] = [tfo['seq'] for tfo in target_seqfos]

    return final_line

# ----------------------------------------------------------------------------------------
def simulate():

    rearrange()

    glfo, naive_event_list, cpath = utils.read_output(naive_fname())
    assert len(naive_event_list) == args.n_sim_events

    outdirs = ['%s/event-%d' % (simdir(), i) for i in range(len(naive_event_list))]

    start = time.time()
    cmdfos = []
    if args.n_procs > 1:
        print '    starting %d events' % len(naive_event_list)
    uid_str_len = 6 + int(math.log(len(naive_event_list), 10))  # if the final sample's going to contain many trees, it's worth making the uids longer so there's fewer collisions/duplicates
    for ievent, (naive_line, outdir) in enumerate(zip(naive_event_list, outdirs)):
        if args.n_sim_events > 1 and args.n_procs == 1:
            print '  %s %d' % (utils.color('blue', 'ievent'), ievent)
        cfo = run_bcr_phylo(naive_line, outdir, ievent, len(naive_event_list), uid_str_len=uid_str_len)  # if n_procs > 1, doesn't run, just returns cfo
        if cfo is not None:
            print '      %s %s' % (utils.color('red', 'run'), cfo['cmd_str'])
            cmdfos.append(cfo)
    if args.n_procs > 1 and len(cmdfos) > 0:
        utils.run_cmds(cmdfos, shell=True, n_max_procs=args.n_procs, batch_system='slurm' if args.slurm else None, allow_failure=True, debug='print')
    print '  bcr-phylo run time: %.1fs' % (time.time() - start)

    if utils.output_exists(args, simfname(), outlabel='mutated simu', offset=4):  # i guess if it crashes during the plotting just below, this'll get confused
        return

    start = time.time()
    mutated_events = []
    for ievent, (naive_line, outdir) in enumerate(zip(naive_event_list, outdirs)):
        mutated_events.append(parse_bcr_phylo_output(glfo, naive_line, outdir, ievent))
    print '  parsing time: %.1fs' % (time.time() - start)

    print '  writing annotations to %s' % simfname()
    utils.write_annotations(simfname(), glfo, mutated_events, utils.simulation_headers)

    if not args.only_csv_plots:
        import lbplotting
        for outdir, event in zip(outdirs, mutated_events):
            lbplotting.plot_bcr_phylo_simulation(outdir, event, args.extrastr, lbplotting.metric_for_target_distance_labels[args.metric_for_target_distance])
        # utils.simplerun('cp -v %s/simu_collapsed_runstat_color_tree.svg %s/plots/' % (outdir, outdir))

# ----------------------------------------------------------------------------------------
def cache_parameters():
    if utils.output_exists(args, param_dir() + '/hmm/hmms', outlabel='parameters', offset=4):
        return
    cmd = './bin/partis cache-parameters --infname %s --parameter-dir %s --seed %d --no-indels' % (simfname(), param_dir(), args.seed)  # forbid indels because in the very rare cases when we call them, they're always wrong, and then they screw up the simultaneous true clonal seqs option
    if args.n_procs > 1:
        cmd += ' --n-procs %d' % args.n_procs
    if args.slurm:
        cmd += ' --batch-system slurm'
    if args.n_max_queries is not None:
        cmd += ' --n-max-queries %d' % args.n_max_queries
    utils.simplerun(cmd, debug=True) #, dryrun=True)

# ----------------------------------------------------------------------------------------
def partition():
    if utils.output_exists(args, partition_fname(), outlabel='partition', offset=4):
        return
    cmd = './bin/partis partition --simultaneous-true-clonal-seqs --is-simu --infname %s --parameter-dir %s --outfname %s --seed %d' % (simfname(), param_dir(), partition_fname(), args.seed)
    #  --write-additional-cluster-annotations 0:5  # I don't think there was really a good reason for having this
    if not args.dont_get_tree_metrics:
        cmd += ' --get-tree-metrics --plotdir %s' % (infdir() + '/plots')
    if args.lb_tau is not None:
        cmd += ' --lb-tau %f' % args.lb_tau
    if args.n_procs > 1:
        cmd += ' --n-procs %d' % args.n_procs
    if args.slurm:
        cmd += ' --batch-system slurm'
    if args.n_max_queries is not None:
        cmd += ' --n-max-queries %d' % args.n_max_queries
    utils.simplerun(cmd, debug=True) #, dryrun=True)
    # cmd = './bin/partis get-tree-metrics --outfname %s/partition.yaml' % infdir()
    # utils.simplerun(cmd, debug=True) #, dryrun=True)

# ----------------------------------------------------------------------------------------
all_actions = ('simu', 'cache-parameters', 'partition')
class MultiplyInheritedFormatter(argparse.RawTextHelpFormatter, argparse.ArgumentDefaultsHelpFormatter):
    pass
formatter_class = MultiplyInheritedFormatter
parser = argparse.ArgumentParser(formatter_class=MultiplyInheritedFormatter)
parser.add_argument('--stype', default='selection', choices=('selection', 'neutral'))
parser.add_argument('--actions', default=':'.join(all_actions))
parser.add_argument('--base-outdir', default='%s/partis/bcr-phylo/test' % os.getenv('fs', default=os.getenv('HOME')))
parser.add_argument('--debug', type=int, default=0, choices=[0, 1, 2])
parser.add_argument('--run-help', action='store_true')
parser.add_argument('--overwrite', action='store_true')
parser.add_argument('--only-csv-plots', action='store_true')
parser.add_argument('--dont-get-tree-metrics', action='store_true', help='Partition without getting tree metrics, presumably because you want to run them yourself later')
parser.add_argument('--seed', type=int, default=1, help='random seed (note that bcr-phylo doesn\'t seem to support setting its random seed)')
parser.add_argument('--n-procs', type=int, default=1)
parser.add_argument('--extrastr', default='simu', help='doesn\'t really do anything, but it\'s required by bcr-phylo')
parser.add_argument('--n-sim-seqs-per-generation', default='100', help='Number of sequences to sample at each time in --obs-times.')
parser.add_argument('--n-sim-events', type=int, default=1, help='number of simulated rearrangement events')
parser.add_argument('--n-max-queries', type=int, help='during parameter caching and partitioning, stop after reading this many queries from simulation file (useful for dtr training samples where we need massive samples to actually train the dtr, but for testing various metrics need far smaller samples).')
parser.add_argument('--obs-times', default='100:120', help='Times (reproductive rounds) at which to selection sequences for observation.')
parser.add_argument('--carry-cap', type=int, default=1000, help='carrying capacity of germinal center')
parser.add_argument('--target-distance', type=int, default=15, help='Desired distance (number of non-synonymous mutations) between the naive sequence and the target sequences.')
parser.add_argument('--metric-for-target-distance', default='aa', choices=['aa', 'nuc', 'aa-sim-ascii', 'aa-sim-blosum'], help='see bcr-phylo docs')
parser.add_argument('--target-count', type=int, default=1, help='Number of target sequences to generate.')
parser.add_argument('--n-target-clusters', type=int, help='number of cluster into which to divide the --target-count target seqs (see bcr-phylo docs)')
parser.add_argument('--min-target-distance', type=int, help='see bcr-phylo docs')
parser.add_argument('--branching-parameter', type=float, default=2., help='see bcr-phylo docs')
parser.add_argument('--base-mutation-rate', type=float, default=0.365, help='see bcr-phylo docs')
parser.add_argument('--selection-strength', type=float, default=1., help='see bcr-phylo docs')
parser.add_argument('--context-depend', type=int, default=0, choices=[0, 1])  # i wish this could be a boolean, but having it int makes it much much easier to interface with the scan infrastructure in cf-tree-metrics.py
parser.add_argument('--paratope-positions', help='see bcr-phylo docs')
parser.add_argument('--restrict-available-genes', action='store_true', help='restrict v and j gene choice to one each (so context dependence is easier to plot)')
parser.add_argument('--lb-tau', type=float, help='')
parser.add_argument('--dont-observe-common-ancestors', action='store_true')
parser.add_argument('--leaf-sampling-scheme', help='see bcr-phylo help')
parser.add_argument('--parameter-variances', help='if set, parameters vary from family to family in one of two ways 1) the specified parameters are drawn from a uniform distribution of the specified width (with mean from the regular argument) for each family. Format example: n-sim-seqs-per-generation,10:carry-cap,150 would give --n-sim-seqs-per-generation +/-5 and --carry-cap +/-75, or 2) parameters for each family are chosen from a \'..\'-separated list, e.g. obs-times,75..100..150')
parser.add_argument('--slurm', action='store_true')

args = parser.parse_args()

if args.seed is not None:
    numpy.random.seed(args.seed)
args.obs_times = utils.get_arg_list(args.obs_times, intify=True)
args.n_sim_seqs_per_generation = utils.get_arg_list(args.n_sim_seqs_per_generation, intify=True)
args.actions = utils.get_arg_list(args.actions, choices=all_actions)
args.parameter_variances = utils.get_arg_list(args.parameter_variances, key_val_pairs=True, choices=['selection-strength', 'obs-times', 'n-sim-seqs-per-generation', 'carry-cap', 'metric-for-target-distance'])  # if you add more, make sure the bounds enforcement and conversion stuff in get_vpar_val() are still ok

assert args.extrastr == 'simu'  # I think at this point this actually can't be changed without changing some other things

# ----------------------------------------------------------------------------------------
if 'simu' in args.actions:
    simulate()
if 'cache-parameters' in args.actions:
    cache_parameters()
if 'partition' in args.actions:
    partition()
