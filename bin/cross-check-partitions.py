#!/usr/bin/env python
import csv
import sys
csv.field_size_limit(sys.maxsize)  # make sure we can write very large csv fields
import argparse
import numpy
import itertools
import colored_traceback.always

# # example usage:
# fsd=/fh/fast/matsen_e/processed-data/partis
# ./bin/cross-check-partitions.py \
#     --locus igh \
#     --min-cluster-sizes 150:5 --max-cdr3-distance 5 \
#     --param $fsd/laura-mb/v17/Hs-LN-D-5RACE-IgG:$fsd/laura-mb-2/v17/BF520-g-M9 \
#     --labels laura-mb-D:laura-mb-2-M9 \
#     --infiles $fsd/laura-mb/v17/partitions/Hs-LN-D-5RACE-IgG-isub-2/partition.csv:$fsd/laura-mb-2/v17/partitions/BF520-g-M9-isub-2/partition.csv

partis_path = '.'  # edit this if you're not running from the main partis dir
sys.path.insert(1, partis_path + '/python')
import utils
import glutils
from clusterpath import ClusterPath

parser = argparse.ArgumentParser()
parser.add_argument('--infiles')
parser.add_argument('--labels')
parser.add_argument('--locus')
parser.add_argument('--parameter-dirs')
parser.add_argument('--min-outer-size', default=10, type=int)
parser.add_argument('--min-inner-size', default=5, type=int)
parser.add_argument('--min-outer-rep-frac', type=float)
parser.add_argument('--min-inner-rep-frac', type=float)
parser.add_argument('--max-cdr3-distance', default=5, type=int, help='ignore clusters with a cdr3 that differs by more than this many nucleotides')
args = parser.parse_args()

args.infiles = utils.get_arg_list(args.infiles)
args.labels = utils.get_arg_list(args.labels)
args.parameter_dirs = utils.get_arg_list(args.parameter_dirs)
assert len(args.infiles) == len(args.labels)
if len(args.parameter_dirs) == 1:
    print '  note: using same glfo for all infiles'
    args.parameter_dirs = [args.parameter_dirs[0] for _ in args.labels]
assert len(args.parameter_dirs) == len(args.labels)

glfos = [glutils.read_glfo(pdir + '/hmm/germline-sets', locus=args.locus) for pdir in args.parameter_dirs]

# ----------------------------------------------------------------------------------------
def getkey(uid_list):
    return ':'.join(uid_list)

# ----------------------------------------------------------------------------------------
def read_annotations(fname, glfo):
    annotations = {}
    with open(fname.replace('.csv', '-cluster-annotations.csv')) as csvfile:
        reader = csv.DictReader(csvfile)
        for line in reader:  # there's a line for each cluster
            if line['v_gene'] == '':  # failed (i.e. couldn't find an annotation)
                continue
            utils.process_input_line(line)  # converts strings in the csv file to floats/ints/dicts/etc.
            utils.add_implicit_info(glfo, line)  # add stuff to <line> that's useful, isn't written to the csv since it's redundant
            # utils.print_reco_event(line)  # print ascii-art representation of the rearrangement event
            annotations[getkey(line['unique_ids'])] = line
    return annotations

# ----------------------------------------------------------------------------------------
def naive_cdr3(info):
    naiveseq, _ = utils.subset_sequences(info, iseq=0, restrict_to_region='cdr3')
    return naiveseq

# ----------------------------------------------------------------------------------------
def naive_hdist_or_none(line1, line2):
    if line1['cdr3_length'] != line2['cdr3_length']:
        return None
    hdist = utils.hamming_distance(naive_cdr3(line1), naive_cdr3(line2))
    if hdist > args.max_cdr3_distance:
        return None
    return hdist

# ----------------------------------------------------------------------------------------
def cdr3_translation(info):
    naive_cdr3_seq = naive_cdr3(info)
    naive_cdr3_seq = naive_cdr3_seq[3 : len(naive_cdr3_seq) - 3]
    if len(naive_cdr3_seq) % 3 != 0:
        # print '  out of frame: adding %s' % ((3 - len(naive_cdr3_seq) % 3) * 'N')
        naive_cdr3_seq += (3 - len(naive_cdr3_seq) % 3) * 'N'
    return utils.ltranslate(naive_cdr3_seq)

# ----------------------------------------------------------------------------------------
cpaths = [ClusterPath() for _ in range(len(args.infiles))]
for ifile in range(len(args.infiles)):
    cpaths[ifile].readfile(args.infiles[ifile])
partitions = [sorted(cp.partitions[cp.i_best], key=len, reverse=True) for cp in cpaths]

repertoire_sizes = [sum([len(c) for c in partition]) for partition in partitions]
min_inner_sizes = [args.min_inner_size if args.min_inner_rep_frac is None else args.min_inner_rep_frac * repertoire_sizes[isample] for isample in range(len(args.infiles))]
min_outer_sizes = [args.min_outer_size if args.min_outer_rep_frac is None else args.min_outer_rep_frac * repertoire_sizes[isample] for isample in range(len(args.infiles))]
max_label_width = max([len(l) for l in args.labels])
label_strs = [('%' + str(max_label_width) + 's') % l for l in args.labels]
print (' %' + str(max_label_width) + 's         total    min cluster') % ''
print (' %' + str(max_label_width) + 's    size   outer  inner') % 'sample'
for isample in range(len(partitions)):
    print '  %s %6d    %3d  %3d' % (label_strs[isample], repertoire_sizes[isample], min_outer_sizes[isample], min_inner_sizes[isample])

partitions = [[c for c in partitions[isample] if len(c) > min_inner_sizes[isample]] for isample in range(len(partitions))]
annotations = [read_annotations(args.infiles[ifn], glfos[ifn]) for ifn in range(len(args.infiles))]

nearest_cluster_lists = {l1 : {l2 : [] for l2 in args.labels if l2 != l1} for l1 in args.labels}
for if1 in range(len(args.infiles)):
    label1 = args.labels[if1]
    print '%s' % utils.color('green', label1)
    for if2 in range(len(args.infiles)):
        if if1 == if2:
            continue
        label2 = args.labels[if2]
        print '\n       %5s      %5s    cdr3' % ('', utils.color('green', label2, width=5))
        print '     size index  size index  dist'
        for cluster1 in partitions[if1]:  # for each cluster in the first partition
            if len(cluster1) < min_outer_sizes[if1]:
                continue
            info1 = annotations[if1][getkey(cluster1)]
            def keyfcn(c2):
                return naive_hdist_or_none(info1, annotations[if2][getkey(c2)])
            sorted_clusters = sorted([c for c in partitions[if2] if keyfcn(c) is not None], key=keyfcn)  # make a list of the clusters in the other partition that's sorted by how similar their naive sequence are
            nearest_cluster_lists[label1][label2].append(sorted_clusters)

            extra_str = ''
            inner_loop_str = ''
            if len(sorted_clusters) == 0:
                # extra_str = utils.color('yellow', '-', width=3)
                inner_loop_str = utils.color('yellow', '-    -', width=8)
            size_index_str = '%s %3d' % (utils.color('blue', '%4d' % len(cluster1)), partitions[if1].index(cluster1))
            print '  %-3s%s   %8s        %-30s%3s' % (extra_str, size_index_str, inner_loop_str, cdr3_translation(info1), extra_str)
            for nclust in sorted_clusters:
                nclust_naive_cdr3 = cdr3_translation(annotations[if2][getkey(nclust)])
                hdist = naive_hdist_or_none(info1, annotations[if2][getkey(nclust)])
                print '               %s %4d   %2s   %-30s' % (utils.color('blue', '%4d' % len(nclust)), partitions[if2].index(nclust), '%d' % hdist if hdist > 0 else '',
                                                                utils.color_mutants(cdr3_translation(info1), nclust_naive_cdr3, amino_acid=True))
