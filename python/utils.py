import yaml
import platform
import resource
import psutil
import numpy
import tempfile
import string
import time
import sys
import os
import random
import itertools
import ast
import math
import glob
from collections import Counter
from collections import OrderedDict
import csv
import subprocess
import multiprocessing
import copy
import traceback
import json
import types
import collections
import operator

import indelutils
import clusterpath
import treeutils

# ----------------------------------------------------------------------------------------
def get_partis_dir():
    return os.path.dirname(os.path.realpath(__file__)).replace('/python', '')

# ----------------------------------------------------------------------------------------
def fsdir():
    fsdir = '/fh/fast/matsen_e'
    if not os.path.exists(fsdir):
        fsdir = '/tmp'
    if os.getenv('USER') is not None:
        fsdir += '/' + os.getenv('USER')
    return fsdir

# ----------------------------------------------------------------------------------------
def choose_random_subdir(dirname, make_dir=False):
    subname = str(random.randint(0, 999999))
    while os.path.exists(dirname + '/' + subname):
        subname = str(random.randint(0, 999999))
    if make_dir:
        prep_dir(dirname + '/' + subname)
    return dirname + '/' + subname

# ----------------------------------------------------------------------------------------
def timeprinter(fcn):
    def wrapper(*args, **kwargs):
        start = time.time()
        # print fcn.__name__,
        fcn(*args, **kwargs)
        print '    %s: (%.1f sec)' % (fcn.__name__, time.time()-start)
    return wrapper

# ----------------------------------------------------------------------------------------
# putting these up here so glutils import doesn't fail... I think I should be able to do it another way, though
regions = ['v', 'd', 'j']
constant_regions = ['c', 'm', 'g', 'a', 'd', 'e']  # NOTE d is in here, which is stupid but necessary, so use is_constant_gene()
loci = collections.OrderedDict((
    ('igh', 'vdj'),
    ('igk', 'vj'),
    ('igl', 'vj'),
    ('tra', 'vj'),
    ('trb', 'vdj'),
    ('trg', 'vj'),
    ('trd', 'vdj'),
))
isotypes = ['m', 'g', 'k', 'l']
locus_pairs = {'ig' : [['igh', 'igk'], ['igh', 'igl']],
               'tr' : [['trb', 'tra'], ['trd', 'trg']]}
# ----------------------------------------------------------------------------------------
def sub_loci(ig_or_tr):  # ok i probably should have just split <loci> by ig/tr, but too late now
    return [l for l in loci if ig_or_tr in l]

def getregions(locus):  # for clarity, don't use the <loci> dictionary directly to access its .values()
    return list(loci[locus])  # doesn't really need to be a list, but it's more clearly analagous to regions & co that way

def has_d_gene(locus):  # for clarity, don't use the <loci> dictionary directly to access its .values()
    return 'd' in loci[locus]

def get_boundaries(locus):  # NOTE almost everything still uses the various static boundaries variables, rather than calling this. It may or may not be more sensible to switch to this eventually
    rlist = getregions(locus)
    return [rlist[i] + rlist[i+1] for i in range(len(rlist)-1)]

def region_pairs(locus):
    return [{'left' : bound[0], 'right' : bound[1]} for bound in get_boundaries(locus)]

import seqfileopener
import glutils
import prutils

#----------------------------------------------------------------------------------------
# NOTE I also have an eps defined in hmmwriter. Simplicity is the hobgoblin of... no, wait, that's just plain ol' stupid to have two <eps>s defined
eps = 1.0e-10  # if things that should be 1.0 are this close to 1.0, blithely keep on keepin on. kinda arbitrary, but works for the moment
def is_normed(probs, this_eps=eps):
    if hasattr(probs, 'keys'):  # if it's a dict, call yourself with a list of the dict's values
        return is_normed([val for val in probs.values()], this_eps=this_eps)
    elif hasattr(probs, '__iter__'):  # if it's a list call yourself with their sum
        return is_normed(sum(probs), this_eps=this_eps)
    else:  # and if it's a float actually do what you're supposed to do
        return math.fabs(probs - 1.0) < this_eps

# ----------------------------------------------------------------------------------------
def pass_fcn(val):  # dummy function for conversions (see beloww)
    return val

# ----------------------------------------------------------------------------------------
def get_arg_list(arg, intify=False, intify_with_ranges=False, floatify=False, translation=None, list_of_lists=False, key_val_pairs=False, choices=None, forbid_duplicates=False):  # make lists from args that are passed as strings of colon-separated values
    if arg is None:
        return None

    convert_fcn = pass_fcn
    if intify:
        convert_fcn = int
    elif intify_with_ranges:  # allow both plain integers and ranges (specied with a dash), e.g. 0:3-6:50 --> 0:3:4:5:50
        def iwr_fcn(vstr):
            if '-' in vstr:
                istart, istop = [int(v) for v in vstr.split('-')]
                return list(range(istart, istop))  # isn't really right, since we still need to flatten this sublist
            else:
                return [int(vstr)]  # make single values list of length one for easier flattening below
        convert_fcn = iwr_fcn
    elif floatify:
        convert_fcn = float

    arglist = arg.strip().split(':')  # to allow ids with minus signs, you can add a space (if you don't use --name=val), which you then have to strip() off
    if list_of_lists or key_val_pairs:
        arglist = [substr.split(',') for substr in arglist]
        if list_of_lists:
            arglist = [[convert_fcn(p) for p in sublist] for sublist in arglist]
    else:
        arglist = [convert_fcn(x) for x in arglist]

    if intify_with_ranges:
        arglist = [v for vl in arglist for v in vl]

    if translation is not None:
        for ia in range(len(arglist)):
            if arglist[ia] in translation:
                arglist[ia] = translation[arglist[ia]]

    if key_val_pairs:
        arglist = {k : convert_fcn(v) for k, v in arglist}

    if choices is not None:  # note that if <key_val_pairs> is set, this (and <forbid_duplicates) is just checking the keys, not the vals
        for arg in arglist:
            if arg not in choices:
                raise Exception('unexpected argument \'%s\' (choices: %s)' % (str(arg), [str(c) for c in choices]))

    if forbid_duplicates:
        if any(arglist.count(a) > 1 for a in arglist):
            raise Exception('duplicate values for arg: %s' % arg)

    return arglist

# ----------------------------------------------------------------------------------------
def add_lists(list_a, list_b):  # add two lists together, except if one is None treat it as if it was zero length (allows to maintain the convention that command line arg variables are None if unset, while still keeping things succinct)
    if list_b is None:
        return copy.deepcopy(list_a)
    elif list_a is None:
        return copy.deepcopy(list_b)
    else:
        return list_a + list_b

# ----------------------------------------------------------------------------------------
def get_single_entry(tl):  # adding this very late, so there's a lot of places it could be used
    assert len(tl) == 1
    return tl[0]

# ----------------------------------------------------------------------------------------
# values used when simulating from scratch (mutation stuff is controlled by command line args, e.g. --scratch-mute-freq)
scratch_mean_erosion_lengths = {'igh' : {'v_3p' : 1.3, 'd_5p' : 5.6, 'd_3p' : 4.7, 'j_5p' : 5.1},
                                'igk' : {'v_3p' : 2.8, 'd_5p' : 1.0, 'd_3p' : 0.0, 'j_5p' : 1.5},
                                'igl' : {'v_3p' : 2.8, 'd_5p' : 1.0, 'd_3p' : 0.0, 'j_5p' : 1.8}}
scratch_mean_insertion_lengths = {l : {'vd' : 5.9 if has_d_gene(l) else 0.,
                                       'dj' : 5.1 if has_d_gene(l) else 1.6}
                                  for l in loci}

real_erosions = ['v_3p', 'd_5p', 'd_3p', 'j_5p']
# NOTE since we now handle v_5p and j_3p deletions by padding with Ns, the hmm does *not* allow actual v_5p and j_3p deletions.
# This means that while we write parameters for v_5p and j_3p deletions to the parameter dir, these are *not* used in making the
# hmm yamels -- which is what we want, because we want to be able to read in short data reads but make full-length simulation.
effective_erosions = ['v_5p', 'j_3p']
all_erosions = real_erosions + effective_erosions
boundaries = ['vd', 'dj']  # NOTE needs to be updated to be consistent with erosion names
effective_boundaries = ['fv', 'jf']
all_boundaries = boundaries + effective_boundaries
nukes = ['A', 'C', 'G', 'T']
ambig_base = 'N'  # this is the only ambiguous base that we allow/use internally
all_ambiguous_bases = list('NRYKMSWBDHV')  # but the other ones are sometimes handled when parsing input, often just by turning them into Ns
ambiguous_amino_acids = ['X', ]
alphabet = set(nukes + [ambig_base])  # NOTE not the greatest naming distinction, but note difference to <expected_characters>
gap_chars = ['.', '-']
expected_characters = set(nukes + [ambig_base] + gap_chars)  # NOTE not the greatest naming distinction, but note difference to <alphabet>
conserved_codons = {l : {'v' : 'cyst',
                         'j' : 'tryp' if l == 'igh' else 'phen'}  # e.g. heavy chain has tryp, light chain has phen
                     for l in loci}
def get_all_codons():  # i'm only make these two fcns rather than globals since they use fcns that aren't defined til way down below
    return [''.join(c) for c in itertools.product('ACGT', repeat=3)]
def get_all_amino_acids(no_stop=False):
    all_aas = set(ltranslate(c) for c in get_all_codons())  # note: includes stop codons (*)
    if no_stop:
        all_aas.remove('*')
    return all_aas

def cdn(glfo, region):  # returns None for d
    return conserved_codons[glfo['locus']].get(region, None)
def cdn_positions(glfo, region):
    if cdn(glfo, region) is None:
        return None
    return glfo[cdn(glfo, region) + '-positions']
def cdn_pos(glfo, region, gene):
    if cdn(glfo, region) is None:
        return None
    return cdn_positions(glfo, region)[gene]
def gseq(glfo, gene):  # adding this fcn very late in the game, i could really stand to use it in a lot more places (grep for "glfo\['seqs'\]\[.*\]\[")
    return glfo['seqs'][get_region(gene)][gene]
def remove_gaps(seq):
    return ''.join([c for c in seq if c not in gap_chars])
def gap_len(seq):  # NOTE see two gap-counting fcns below (_pos_in_alignment())
    return len([c for c in seq if c in gap_chars])
def non_gap_len(seq):  # NOTE see two gap-counting fcns below (_pos_in_alignment())
    return len(seq) - gap_len(seq)
def ambig_frac(seq):
    # ambig_seq = filter(all_ambiguous_bases.__contains__, seq)
    # return float(len(ambig_seq)) / len(seq)
    return float(seq.count(ambig_base)) / len(seq)

# ----------------------------------------------------------------------------------------
def reverse_complement_warning():
    return '%s maybe need to take reverse complement (partis only searches in forward direction) or set --locus (default is igh). Both of these can be fixed using bin/split-loci.py.' % color('red', 'note:')

codon_table = {
    'cyst' : ['TGT', 'TGC'],
    'tryp' : ['TGG', ],
    'phen' : ['TTT', 'TTC'],
    'stop' : ['TAG', 'TAA', 'TGA']
}
# Infrastrucure to allow hashing all the columns together into a dict key.
# Uses a tuple with the variables that are used to index selection frequencies
# NOTE fv and jf insertions are *effective* (not real) insertions between v or j and the framework. They allow query sequences that extend beyond the v or j regions
index_columns = tuple(['v_gene', 'd_gene', 'j_gene', 'v_5p_del', 'v_3p_del', 'd_5p_del', 'd_3p_del', 'j_5p_del', 'j_3p_del', 'fv_insertion', 'vd_insertion', 'dj_insertion', 'jf_insertion'])

index_keys = {}
for i in range(len(index_columns)):  # dict so we can access them by name instead of by index number
    index_keys[index_columns[i]] = i

# don't think this has been used in a long time
# # ----------------------------------------------------------------------------------------
# def get_codon(fname):
#     codon = fname.split('-')[0]
#     if codon not in [c for locus in loci for c in conserved_codons[locus].values()]:
#         raise Exception('couldn\'t get codon from file name %s' % fname)
#     return codon

# ----------------------------------------------------------------------------------------
# Info specifying which parameters are assumed to correlate with which others. Taken from mutual
# information plot in bcellap repo

# key is parameter of interest, and associated list gives the parameters (other than itself) which are necessary to predict it
# TODO am I even using these any more? I think I might just be using the all-probs file
column_dependencies = {}
column_dependencies['v_gene'] = [] # NOTE v choice actually depends on everything... but not super strongly, so a.t.m. I ignore it
column_dependencies['v_5p_del'] = ['v_gene']
column_dependencies['v_3p_del'] = ['v_gene']
column_dependencies['d_gene'] = []
column_dependencies['d_5p_del'] = ['d_gene']  # NOTE according to the mebcell mutual information plot d_5p_del is also correlated to d_3p_del (but we have no way to model that a.t.m. in the hmm)
column_dependencies['d_3p_del'] = ['d_gene']  # NOTE according to the mebcell mutual information plot d_3p_del is also correlated to d_5p_del (but we have no way to model that a.t.m. in the hmm)
column_dependencies['j_gene'] = []
column_dependencies['j_5p_del'] = ['j_gene']  # NOTE mebcell plot showed this correlation as being small, but I'm adding it here for (a possibly foolish) consistency
column_dependencies['j_3p_del'] = ['j_gene']
column_dependencies['fv_insertion'] = []
column_dependencies['vd_insertion'] = ['d_gene']
column_dependencies['dj_insertion'] = ['j_gene']
column_dependencies['jf_insertion'] = []

# column_dependencies['vd_insertion_content'] = []
# column_dependencies['dj_insertion_content'] = []

# tuples with the column and its dependencies mashed together
# (first entry is the column of interest, and it depends upon the following entries)
column_dependency_tuples = []
for column, deps in column_dependencies.iteritems():
    tmp_list = [column]
    tmp_list.extend(deps)
    column_dependency_tuples.append(tuple(tmp_list))

adaptive_headers = {
    'seqs' : 'nucleotide',
    'v_gene' : 'vMaxResolved',
    'd_gene' : 'dMaxResolved',
    'j_gene' : 'jMaxResolved',
    'v_3p_del' : 'vDeletion',
    'd_5p_del' : 'd5Deletion',
    'd_3p_del' : 'd3Deletion',
    'j_5p_del' : 'jDeletion'
}

# ----------------------------------------------------------------------------------------
forbidden_characters = set([':', ';', ','])  # strings that are not allowed in sequence ids
forbidden_character_translations = string.maketrans(':;,', 'csm')
ambig_translations = string.maketrans(''.join(all_ambiguous_bases), ambig_base * len(all_ambiguous_bases))

functional_columns = ['mutated_invariants', 'in_frames', 'stops']

# ----------------------------------------------------------------------------------------
def useful_bool(bool_str):
    if bool_str == 'True':
        return True
    elif bool_str == 'False':
        return False
    elif bool_str == '1':
        return True
    elif bool_str == '0':
        return False
    else:
        raise Exception('couldn\'t convert \'%s\' to bool' % bool_str)

# ----------------------------------------------------------------------------------------
def get_z_scores(vals):  # return list of <vals> normalized to units of standard deviations (i.e. z scores)
    mean, std = numpy.mean(vals), numpy.std(vals, ddof=1)
    return [(v - mean) / std for v in vals]

# ----------------------------------------------------------------------------------------
def get_str_float_pair_dict(strlist):
    def getpair(pairstr):
        pairlist = pairstr.split(':')
        assert len(pairlist) == 2
        return (pairlist[0], float(pairlist[1]))
    return OrderedDict(getpair(pairstr) for pairstr in strlist)

# ----------------------------------------------------------------------------------------
def get_list_of_str_list(strlist):
    if strlist == '':
        return []
    return [[] if substr == '' else substr.split(':') for substr in strlist]

# keep track of all the *@*@$!ing different keys that happen in the <line>/<hmminfo>/whatever dictionaries
linekeys = {}
# I think 'per_family' is pretty incomplete at this point, but I also think it isn't being used
linekeys['per_family'] = ['naive_seq', 'cdr3_length', 'codon_positions', 'lengths', 'regional_bounds'] + \
                         ['invalid', 'tree', 'consensus_seq', 'consensus_seq_aa', 'naive_seq_aa', 'cons_dists_nuc', 'cons_dists_aa'] + \
                         [r + '_gene' for r in regions] + \
                         [e + '_del' for e in all_erosions] + \
                         [b + '_insertion' for b in all_boundaries] + \
                         [r + '_gl_seq' for r in regions] + \
                         [r + '_per_gene_support' for r in regions]
# NOTE some of the indel keys are just for writing to files, whereas 'indelfos' is for in-memory
# note that, as a list of gene matches, all_matches would in principle be per-family, except that it's sw-specific, and sw is all single-sequence
linekeys['per_seq'] = ['seqs', 'unique_ids', 'mut_freqs', 'n_mutations', 'input_seqs', 'indel_reversed_seqs', 'cdr3_seqs', 'full_coding_input_seqs', 'padlefts', 'padrights', 'indelfos', 'duplicates',
                       'has_shm_indels', 'qr_gap_seqs', 'gl_gap_seqs', 'multiplicities', 'timepoints', 'affinities', 'subjects', 'constant-regions', 'relative_affinities', 'lambdas', 'nearest_target_indices', 'all_matches', 'seqs_aa', 'cons_dists_nuc', 'cons_dists_aa'] + \
                      [r + '_qr_seqs' for r in regions] + \
                      ['aligned_' + r + '_seqs' for r in regions] + \
                      functional_columns
linekeys['hmm'] = ['logprob', 'errors', 'tree-info', 'alternative-annotations'] + [r + '_per_gene_support' for r in regions]
linekeys['sw'] = ['k_v', 'k_d', 'all_matches', 'padlefts', 'padrights']
linekeys['simu'] = ['reco_id', 'affinities', 'relative_affinities', 'lambdas', 'tree', 'target_seqs', 'nearest_target_indices']

# keys that are added by add_implicit_info()
implicit_linekeys = set(['naive_seq', 'cdr3_length', 'codon_positions', 'lengths', 'regional_bounds', 'invalid', 'indel_reversed_seqs'] + \
                        [r + '_gl_seq' for r in regions] + \
                        ['mut_freqs', 'n_mutations'] + functional_columns + [r + '_qr_seqs' for r in regions] + ['aligned_' + r + '_seqs' for r in regions])

extra_annotation_headers = [  # you can specify additional columns (that you want written to csv) on the command line from among these choices (in addition to <annotation_headers>)
    'cdr3_seqs',
    'full_coding_naive_seq',
    'full_coding_input_seqs',
    'linearham-info',
    'consensus_seq',
    'consensus_seq_aa',
    'naive_seq_aa',
    'seqs_aa',
    'cons_dists_nuc',
    'cons_dists_aa',
] + list(implicit_linekeys)  # NOTE some of the ones in <implicit_linekeys> are already in <annotation_headers>

linekeys['extra'] = extra_annotation_headers
all_linekeys = set([k for cols in linekeys.values() for k in cols])

input_metafile_keys = {  # map between the key we want the user to put in the meta file, and the key we use in the regular <line> dicts (basically just pluralizing)
    'affinity' : 'affinities',  # should maybe add all of these to <annotation_headers>?
    'relative_affinity' : 'relative_affinities',
    'timepoint' : 'timepoints',
    'multiplicity' : 'multiplicities',
    'subject' : 'subjects',
    'constant-region' : 'constant-regions',
}
reversed_input_metafile_keys = {v : k for k, v in input_metafile_keys.items()}

# ----------------------------------------------------------------------------------------
special_indel_columns_for_output = ['has_shm_indels', 'qr_gap_seqs', 'gl_gap_seqs', 'indel_reversed_seqs']  # arg, ugliness (but for reasons...)
annotation_headers = ['unique_ids', 'invalid', 'v_gene', 'd_gene', 'j_gene', 'cdr3_length', 'mut_freqs', 'n_mutations', 'input_seqs', 'indel_reversed_seqs', 'has_shm_indels', 'qr_gap_seqs', 'gl_gap_seqs', 'naive_seq', 'duplicates'] \
                     + [r + '_per_gene_support' for r in regions] \
                     + [e + '_del' for e in all_erosions] + [b + '_insertion' for b in all_boundaries] \
                     + functional_columns + input_metafile_keys.values() \
                     + ['codon_positions', 'tree-info', 'alternative-annotations']
simulation_headers = linekeys['simu'] + [h for h in annotation_headers if h not in linekeys['hmm']]
sw_cache_headers = [h for h in annotation_headers if h not in linekeys['hmm']] + linekeys['sw']
partition_cachefile_headers = ('unique_ids', 'logprob', 'naive_seq', 'naive_hfrac', 'errors')  # these have to match whatever bcrham is expecting (in packages/ham/src/glomerator.cc, ReadCacheFile() and WriteCacheFile())
bcrham_dbgstrs = {
    'partition' : {  # corresponds to stdout from glomerator.cc
        'read-cache' : ['logprobs', 'naive-seqs'],
        'calcd' : ['vtb', 'fwd', 'hfrac'],
        'merged' : ['hfrac', 'lratio'],
        'time' : ['bcrham', ]
    },
    'annotate' : {  # corresponds to stdout from, uh, trellis.cc or something
        'calcd' : ['vtb', 'fwd'],
        'time' : ['bcrham', ]
    },
}
bcrham_dbgstr_types = {
    'partition' : {
        'sum' : ['calcd', 'merged'],  # for these ones, sum over all procs
        'same' : ['read-cache', ],  # check that these are the same for all procs
        'min-max' : ['time', ]
    },
    'annotate' : {  # strict subset of the 'partition' ones
        'sum' : ['calcd', ],
        'same' : [],
        'min-max' : ['time', ]
    },
}

# ----------------------------------------------------------------------------------------
io_column_configs = {
    'ints' : ['n_mutations', 'cdr3_length', 'padlefts', 'padrights'] + [e + '_del' for e in all_erosions],
    'floats' : ['logprob', 'mut_freqs'],
    'bools' : functional_columns + ['has_shm_indels', 'invalid'],
    'literals' : ['indelfo', 'indelfos', 'k_v', 'k_d', 'all_matches', 'alternative-annotations'],  # simulation has indelfo[s] singular, annotation output has it plural... and I think it actually makes sense to have it that way
    'lists-of-lists' : ['duplicates'] + [r + '_per_gene_support' for r in regions],  # NOTE that some keys are in both 'lists' and 'lists-of-lists', e.g. 'duplicates'. This is now okish, since the ordering in the if/else statements is now the same in both get_line_for_output() and process_input_line(), but it didn't used to be so there's probably files lying around that have it screwed up). It would be nice to not have it this way, but (especially for backwards compatibility) it's probably best not to mess with it.
    'lists' : [k for k in linekeys['per_seq'] if k not in ['indelfos', 'all_matches']],  # indelfos and all_matches are lists, but we can't just split them by colons since they have colons within the dict string
}

# NOTE these are all *input* conversion functions (for ouput we mostly just call str())
# also NOTE these only get used on deprecated csv output files
conversion_fcns = {}
for key in io_column_configs['ints']:
    conversion_fcns[key] = int
for key in io_column_configs['floats']:
    conversion_fcns[key] = float
for key in io_column_configs['bools']:
    conversion_fcns[key] = useful_bool
for key in io_column_configs['literals']:
    conversion_fcns[key] = ast.literal_eval
for region in regions:
    conversion_fcns[region + '_per_gene_support'] = get_str_float_pair_dict
conversion_fcns['duplicates'] = get_list_of_str_list

# ----------------------------------------------------------------------------------------
def get_annotation_dict(annotation_list, duplicate_resolution_key=None):
    annotation_dict = OrderedDict()
    for line in annotation_list:
        uidstr = ':'.join(line['unique_ids'])
        if uidstr in annotation_dict or duplicate_resolution_key is not None:  # if <duplicate_resolution_key> was specified, but it wasn't specified properly (e.g. if it's not sufficient to resolve duplicates), then <uidstr> won't be in <annotation_dict>
            if duplicate_resolution_key is None:
                print '  %s multiple annotations for the same cluster, but no duplication resolution key was specified, so returning None for annotation dict (which is fine, as long as you\'re not then trying to use it)' % color('yellow', 'warning')
                return None
            else:
                uidstr = '%s-%s' % (uidstr, line[duplicate_resolution_key])
                if uidstr in annotation_dict:
                    raise Exception('duplicate key even after adding duplicate resolution key: \'%s\'' % uidstr)
        assert uidstr not in annotation_dict
        annotation_dict[uidstr] = line
    return annotation_dict

# ----------------------------------------------------------------------------------------
def per_seq_val(line, key, uid):  # get value for per-sequence key <key> corresponding to <uid> NOTE now I've written this, I should really go through and use it in all the places where I do it by hand
    if key not in linekeys['per_seq']:
        raise Exception('key \'%s\' not in per-sequence keys' % key)
    return line[key][line['unique_ids'].index(uid)]  # NOTE just returns the first one, idgaf if there's more than one (and maybe I won't regret that...)

# ----------------------------------------------------------------------------------------
def n_dups(line):  # number of duplicate sequences summed over all iseqs (note: duplicates do not include the actual uids/sequences in the annotation) UPDATE: they also don't include 'multiplicities'
    return len([u for dlist in line['duplicates'] for u in dlist])

# ----------------------------------------------------------------------------------------
def uids_and_dups(line):  # NOTE it's kind of weird to have this ignore 'multiplicites' (if it's set), but I'm pretty sure the places this fcn gets used in treeutils only want 'duplicates' included
    return line['unique_ids'] + [u for dlist in line['duplicates'] for u in dlist]

# ----------------------------------------------------------------------------------------
def get_multiplicity(line, uid=None, iseq=None):  # combines duplicates with any input meta info multiplicities (well, the 'multiplicities' key in <line> should already have them combined [see waterer])
    if uid is None:
        def ifcn(k): return line[k][iseq]
    elif iseq is None:
        def ifcn(k): return per_seq_val(line, k, uid)
    else:
        assert False
    if 'multiplicities' in line:  # if there was input meta info passed in
        return None if ifcn('multiplicities') == 'None' else ifcn('multiplicities')  # stupid old style csv files not converting correctly (i know i could fix it in the conversion function but i don't want to touch that stupid old code)
    elif 'duplicates' in line:
        return len(ifcn('duplicates')) + 1
    else: # this can probably only happen on very old files (e.g. it didn't used to get added to simulation)
        return 1

# ----------------------------------------------------------------------------------------
def get_multiplicities(line):  # combines duplicates with any input meta info multiplicities (well, the 'multiplicities' key in <line> should already have them combined [see waterer])
    return [get_multiplicity(line, iseq=i) for i in range(len(line['unique_ids']))]

# ----------------------------------------------------------------------------------------
def synthesize_single_seq_line(line, iseq):
    """ without modifying <line>, make a copy of it corresponding to a single-sequence event with the <iseq>th sequence """
    singlefo = {}
    for key in line:
        if key in linekeys['per_seq']:
            singlefo[key] = [line[key][iseq], ]  # used to also deepcopy the per-seq value, but it's really slow and i really think there's no reason to
        else:
            singlefo[key] = copy.deepcopy(line[key])
    return singlefo

# ----------------------------------------------------------------------------------------
def synthesize_multi_seq_line_from_reco_info(uids, reco_info):  # assumes you already added all the implicit info
    assert len(uids) > 0
    multifo = copy.deepcopy(reco_info[uids[0]])
    for col in [c for c in linekeys['per_seq'] if c in multifo]:
        assert [len(reco_info[uid][col]) for uid in uids].count(1) == len(uids)  # make sure every uid's info for this column is of length 1
        multifo[col] = [copy.deepcopy(reco_info[uid][col][0]) for uid in uids]
    return multifo

# ----------------------------------------------------------------------------------------
# add seqs in <seqfos_to_add> to the annotation in <line>, aligning new seqs against <line>'s naive seq with mafft if necessary (see bin/add-seqs-to-outputs.py)
# NOTE see also replace_seqs_in_line()
# NOTE also that there's no way to add shm indels for seqs in <seqfos_to_add>
def add_seqs_to_line(line, seqfos_to_add, glfo, try_to_fix_padding=False, refuse_to_align=False, debug=False):
    # ----------------------------------------------------------------------------------------
    def align_sfo_seqs(sfos_to_align):
        sfos_to_align['naive_seq'] = line['naive_seq']
        msa_info = align_many_seqs([{'name' : n, 'seq' : s} for n, s in sfos_to_align.items()])
        aligned_naive_seq = get_single_entry([sfo['seq'] for sfo in msa_info if sfo['name'] == 'naive_seq'])
        msa_info = [sfo for sfo in msa_info if sfo['name'] != 'naive_seq']
        if debug:
            print '  aligned %d seq%s with length different to naive sequence:' % (len(sfos_to_align) - 1, plural(len(sfos_to_align) - 1))
            for iseq, sfo in enumerate(msa_info):
                color_mutants(aligned_naive_seq, sfo['seq'], print_result=True, ref_label='naive seq ', seq_label=sfo['name']+' ', extra_str='        ', only_print_seq=iseq>0)
        for sfo in msa_info:
            trimmed_seq = []  # it could be padded too, but probably it'll mostly be trimmed, so we just call it that
            for naive_nuc, new_nuc in zip(aligned_naive_seq, sfo['seq']):
                if naive_nuc in gap_chars:  # probably extra crap on the ends of the new sequence
                    continue
                elif new_nuc in gap_chars:  # naive seq probably has some N padding
                    trimmed_seq.append(ambig_base)
                else:
                    trimmed_seq.append(new_nuc)
            sfos_to_align[sfo['name']] = ''.join(trimmed_seq)
            assert len(sfos_to_align[sfo['name']]) == len(line['naive_seq'])

    # ----------------------------------------------------------------------------------------
    def getseq(sfo):  # could use recursive .get(, .get()), but i just feel like making it more explicit
        # trimmed_seqfos.get(sfo['name'], sfos_to_align.get(sfo['name'], sfo['seq'])
        if sfo['name'] in trimmed_seqfos:
            return trimmed_seqfos[sfo['name']]
        elif sfo['name'] in sfos_to_align:
            return sfos_to_align[sfo['name']]
        else:
            return sfo['seq']

    # ----------------------------------------------------------------------------------------
    trimmed_seqfos, sfos_to_align = {}, {}
    if try_to_fix_padding:
        for sfo in [s for s in seqfos_to_add if len(s['seq']) > len(line['naive_seq'])]:
            trimmed_seq = remove_ambiguous_ends(sfo['seq'])
            if len(trimmed_seq) == len(line['naive_seq']):  # presumably the naive seq matches any seqs that are already in <line> (and inserts and deletions and whatnot), so we can probably only really fix it if the new seqs are padded but the naive seq isn't
                trimmed_seqfos[sfo['name']] = trimmed_seq
        if debug:
            print '    trimmed %d seq%s to same length as naive seq' % (len(trimmed_seqfos), plural(len(trimmed_seqfos)))
    if not refuse_to_align:
        sfos_to_align = {sfo['name'] : sfo['seq'] for sfo in seqfos_to_add if sfo['name'] not in trimmed_seqfos and len(sfo['seq']) != len(line['naive_seq'])}  # implicit info adding enforces that the naive seq is the same length as all the seqs
        if len(sfos_to_align) > 0:
            align_sfo_seqs(sfos_to_align)
    aligned_seqfos = [{'name' : sfo['name'], 'seq' : getseq(sfo)} for sfo in seqfos_to_add]  # NOTE needs to be in same order as <seqfos_to_add>

    remove_all_implicit_info(line)

    for key in set(line) & set(linekeys['per_seq']):
        if key == 'unique_ids':
            line[key] += [s['name'] for s in aligned_seqfos]
        elif key == 'input_seqs' or key == 'seqs':  # i think elsewhere these end up pointing to the same list of string objects, but i think that doesn't matter?
            line[key] += [s['seq'] for s in aligned_seqfos]
        elif key == 'duplicates':
            line[key] += [[] for _ in aligned_seqfos]
        elif key == 'indelfos':
            line[key] += [indelutils.get_empty_indel() for _ in aligned_seqfos]
        else:  # I think this should only be for input meta keys like multiplicities, affinities, and timepoints, and hopefully they can all handle None?
            line[key] += [None for _ in aligned_seqfos]

    add_implicit_info(glfo, line)

    if debug:
        print_reco_event(line, label='after adding %d seq%s:'%(len(aligned_seqfos), plural(len(aligned_seqfos))), extra_str='      ', queries_to_emphasize=[s['name'] for s in aligned_seqfos])

# ----------------------------------------------------------------------------------------
# same as add_seqs_to_line(), except this removes all existing seqs first, so the final <line> only contains the seqs in <seqfos_to_add>
# NOTE this removes any existing per-seq info in <line>, e.g. shm indels (of course, since they pertain only to seqs that we're removing)
def replace_seqs_in_line(line, seqfos_to_add, glfo, try_to_fix_padding=False, refuse_to_align=False, debug=False):
    n_seqs_to_remove = len(line['unique_ids'])
    add_seqs_to_line(line, seqfos_to_add, glfo, try_to_fix_padding=try_to_fix_padding, refuse_to_align=refuse_to_align, debug=debug)
    iseqs_to_keep = list(range(n_seqs_to_remove, len(line['unique_ids'])))
    restrict_to_iseqs(line, iseqs_to_keep, glfo)

# ----------------------------------------------------------------------------------------
def get_repfracstr(csize, repertoire_size):  # return a concise string representing <csize> / <repertoire_size>
    repfrac = float(csize) / repertoire_size
    denom = int(1. / repfrac)
    estimate = 1. / denom
    frac_error = (estimate - repfrac) / repfrac
    if frac_error > 0.10:  # if it's more than 10% off just use the float str
        # print 'pretty far off: (1/denom - repfrac) / repfrac = (1./%d - %f) / %f = %f' % (denom, repfrac, repfrac, frac_error)
        repfracstr = '%.2f' % repfrac
    elif denom > 1000:
        repfracstr = '%.0e' % repfrac
    else:
        repfracstr = '1/%d' % denom
    return repfracstr

# ----------------------------------------------------------------------------------------
def generate_dummy_v(d_gene):
    pv, sv, al = split_gene(d_gene)
    return get_locus(d_gene).upper() + 'VxDx' + pv + '-' + sv + '*' + al

# ----------------------------------------------------------------------------------------
# NOTE see seqfileopener.py or treeutils.py for example usage (both args should be set to None the first time through)
def choose_new_uid(potential_names, used_names, initial_length=1, shuffle=False):
    # NOTE only need to set <initial_length> for the first call -- after that if you're reusing the same <potential_names> and <used_names> there's no need (but it's ok to set it every time, as long as it has the same value)
    # NOTE setting <shuffle> will shuffle every time, i.e. it's designed such that you call with shuffle *once* before starting
    def get_potential_names(length):
        return [''.join(ab) for ab in itertools.combinations(string.ascii_lowercase, length)]
    if potential_names is None:  # first time through
        potential_names = get_potential_names(initial_length)
        used_names = []
    if len(potential_names) == 0:  # ran out of names
        potential_names = get_potential_names(len(used_names[-1]) + 1)
    if len(potential_names[0]) < initial_length:
        raise Exception('choose_new_uid(): next potential name \'%s\' is shorter than the specified <initial_length> %d (this is probably only possible if you called this several times with different <initial_length> values [which you shouldn\'t do])' % (potential_names[0], initial_length))
    if shuffle:
        random.shuffle(potential_names)
    new_id = potential_names.pop(0)
    used_names.append(new_id)
    return new_id, potential_names, used_names

# ----------------------------------------------------------------------------------------
def convert_from_adaptive_headers(glfo, line, uid=None, only_dj_rearrangements=False):
    newline = {}
    print_it = False

    for head, ahead in adaptive_headers.items():
        newline[head] = line[ahead]
        if head in io_column_configs['lists']:
            newline[head] = [newline[head], ]

    if uid is not None:
        newline['unique_ids'] = [uid, ]

    for erosion in real_erosions:
        newline[erosion + '_del'] = int(newline[erosion + '_del'])
    newline['v_5p_del'] = 0
    newline['j_3p_del'] = 0

    for region in regions:
        if newline[region + '_gene'] == 'unresolved':
            newline[region + '_gene'] = None
            continue
        if region == 'j' and 'P' in newline[region + '_gene']:
            newline[region + '_gene'] = newline[region + '_gene'].replace('P', '')

        if '*' not in newline[region + '_gene']:
            # print uid
            # tmpheads = ['dMaxResolved', 'dFamilyName', 'dGeneName', 'dGeneAllele', 'dFamilyTies', 'dGeneNameTies', 'dGeneAlleleTies']
            # for h in tmpheads:
            #     print '   %s: %s' % (h, line[h]),
            # print ''
            if line['dGeneAlleleTies'] == '':
                newline['failed'] = True
                return newline
            d_alleles = line['dGeneAlleleTies'].split(',')
            newline[region + '_gene'] += '*' + d_alleles[0]
        primary_version, sub_version, allele = split_gene(newline[region + '_gene'])
        primary_version, sub_version = primary_version.lstrip('0'), sub_version.lstrip('0')  # alleles get to keep their leading zero (thank you imgt for being consistent)
        if region == 'j':  # adaptive calls every j sub_version 1
            sub_version = None
        gene = rejoin_gene(glfo['locus'], region, primary_version, sub_version, allele)
        if gene not in glfo['seqs'][region]:
            gene = glutils.convert_to_duplicate_name(glfo, gene)
        if gene not in glfo['seqs'][region]:
            raise Exception('couldn\'t rebuild gene name from adaptive data: %s' % gene)
        newline[region + '_gene'] = gene

    seq = newline['seqs'][0]
    boundlist = ['vIndex', 'n1Index', 'dIndex', 'n2Index', 'jIndex']
    qrbounds, glbounds = {}, {}
    for region in regions:
        if only_dj_rearrangements and region == 'v':
            if newline['d_gene'] is None:
                newline['failed'] = True
                return newline
            newline['v_gene'] = generate_dummy_v(newline['d_gene'])
            line['vIndex'] = 0
            line['n1Index'] = int(line['dIndex']) - 1  # or is it without the -1?
            glfo['seqs']['v'][newline['v_gene']] = seq[line['vIndex'] : line['n1Index']]
            glfo['cyst-positions'][newline['v_gene']] = len(glfo['seqs']['v'][newline['v_gene']]) - 3
        if newline[region + '_gene'] is None:
            newline['failed'] = True
            return newline
        qrb = [int(line[region + 'Index']),
                    int(line[boundlist[boundlist.index(region + 'Index') + 1]]) if region != 'j' else len(seq)]
        glseq = glfo['seqs'][region][newline[region + '_gene']]
        glb = [newline[region + '_5p_del'],
                    len(glseq) - newline[region + '_3p_del']]
        if region == 'j' and glb[1] - glb[0] > qrb[1] - qrb[0]:  # extra adaptive stuff on right side of j
            old = glb[1]
            glb[1] = glb[0] + qrb[1] - qrb[0]
            newline['j_3p_del'] = old - glb[1]

        if qrb[0] == -1 or qrb[1] == -1 or qrb[1] < qrb[0]:  # should this also be equals?
            newline['failed'] = True
            return newline
        if qrb[1] - qrb[0] != glb[1] - glb[0]:
            newline['failed'] = True
            return newline
        qrbounds[region] = qrb
        glbounds[region] = glb

    for bound in boundaries:
        newline[bound + '_insertion'] = seq[qrbounds[bound[0]][1] : qrbounds[bound[1]][0]]  # end of lefthand region to start of righthand region

    newline['fv_insertion'] = ''
    newline['jf_insertion'] = seq[qrbounds['j'][1]:]

    # print seq
    # print seq[:qrbounds['d'][0]],
    # print seq[qrbounds['d'][0] : qrbounds['d'][1]],
    # print seq[qrbounds['d'][1] : qrbounds['j'][0]],
    # print seq[qrbounds['j'][0] : qrbounds['j'][1]],
    # print seq[qrbounds['j'][1] :]

    newline['indelfos'] = [indelutils.get_empty_indel(), ]

    if print_it:
        add_implicit_info(glfo, newline)
        print_reco_event(newline, label=uid)

    # still need to convert to integers/lists/whatnot (?)

    newline['failed'] = False

    return newline

# ----------------------------------------------------------------------------------------
# definitions here: http://clip.med.yale.edu/changeo/manuals/Change-O_Data_Format.pdf
presto_headers = OrderedDict([  # enforce this ordering so the output files are easier to read
    ('SEQUENCE_ID', 'unique_ids'),
    ('V_CALL', 'v_gene'),
    ('D_CALL', 'd_gene'),
    ('J_CALL', 'j_gene'),
    ('JUNCTION_LENGTH', None),
    ('SEQUENCE_INPUT', 'input_seqs'),
    ('SEQUENCE_IMGT', 'aligned_v_plus_unaligned_dj'),
])

# reference: https://docs.airr-community.org/en/stable/datarep/rearrangements.html#fields
airr_headers = OrderedDict([  # enforce this ordering so the output files are easier to read
    # required:
    ('sequence_id', 'unique_ids'),
    ('sequence', 'input_seqs'),
    ('rev_comp', None),
    ('productive', None),
    ('v_call', 'v_gene'),
    ('d_call', 'd_gene'),
    ('j_call', 'j_gene'),
    ('sequence_alignment', None),
    ('germline_alignment', None),
    ('junction', None),  # NOTE this is *actually* the junction, whereas what partis calls the cdr3 is also actually the junction (which is terrible, but i swear it's not entirely my fault, but either way it's just too hard to change now)
    ('junction_aa', None),
    ('v_cigar', None),
    ('d_cigar', None),
    ('j_cigar', None),
    ('clone_id', None),
    # optional:
    ('vj_in_frame', 'in_frames'),
    ('stop_codon', 'stops'),
    ('locus', None),
    ('np1', 'vd_insertion'),
    ('np2', 'dj_insertion'),
    ('duplicate_count', None),
    ('cdr3_start', None),
    ('cdr3_end', None),
])
for rtmp in regions:
    airr_headers[rtmp+'_support'] = None      # NOTE not really anywhere to put the alternative annotation, which is independent of this and maybe more accurate
    airr_headers[rtmp+'_identity'] = None
    airr_headers[rtmp+'_sequence_start'] = None
    airr_headers[rtmp+'_sequence_end'] = None

linearham_headers = OrderedDict((
    ('Iteration', None),
    ('RBLogLikelihood', None),
    ('Prior', None),
    ('alpha', None),
    ('er[1]', None), ('er[2]', None), ('er[3]', None), ('er[4]', None), ('er[5]', None), ('er[6]', None),
    ('pi[1]', None), ('pi[2]', None), ('pi[3]', None), ('pi[4]', None),
    ('tree', None),
    ('sr[1]', None), ('sr[2]', None), ('sr[3]', None), ('sr[4]', None),
    ('LHLogLikelihood', None),
    ('LogWeight', None),
    ('NaiveSequence', 'naive_seq'),
    ('VGene', 'v_gene'),
    ('V5pDel', 'v_5p_del'),
    ('V3pDel', 'v_3p_del'),
    ('VFwkInsertion', 'fv_insertion'),
    ('VDInsertion', 'vd_insertion'),
    ('DGene', 'd_gene'),
    ('D5pDel', 'd_5p_del'),
    ('D3pDel', 'd_3p_del'),
    ('DJInsertion', 'dj_insertion'),
    ('JGene', 'j_gene'),
    ('J5pDel', 'j_5p_del'),
    ('J3pDel', 'j_3p_del'),
    ('JFwkInsertion', 'jf_insertion'),
))


# ----------------------------------------------------------------------------------------
def get_line_with_presto_headers(line):  # NOTE doesn't deep copy
    """ convert <line> to presto csv format """
    if len(line['unique_ids']) > 1:  # has to happen *before* utils.get_line_for_output()  UPDATE wtf does this mean?
        raise Exception('multiple seqs not handled for presto output')

    presto_line = {}
    for phead, head in presto_headers.items():
        if head == 'aligned_v_plus_unaligned_dj':
            presto_line[phead] = line['aligned_v_seqs'][0] + line['vd_insertion'] + line['d_qr_seqs'][0] + line['dj_insertion'] + line['j_qr_seqs'][0]
        elif phead == 'JUNCTION_LENGTH':
            presto_line[phead] = line['cdr3_length']  # + 6  oops, no +6... what I call cdr3 length is properly junction length (but would be a colossal clusterfuck to change)
        elif head == 'unique_ids' or head == 'input_seqs':
            presto_line[phead] = line[head][0]
        else:
            presto_line[phead] = line[head]

    return presto_line

# ----------------------------------------------------------------------------------------
def write_presto_annotations(outfname, annotation_list, failed_queries):
    print '   writing presto annotations to %s' % outfname
    assert getsuffix(outfname) == '.tsv'  # already checked in processargs.py
    with open(outfname, 'w') as outfile:
        writer = csv.DictWriter(outfile, presto_headers.keys(), delimiter='\t')
        writer.writeheader()

        for line in annotation_list:
            if len(line['unique_ids']) == 1:
                writer.writerow(get_line_with_presto_headers(line))
            else:
                for iseq in range(len(line['unique_ids'])):
                    writer.writerow(get_line_with_presto_headers(synthesize_single_seq_line(line, iseq)))

        # and write empty lines for seqs that failed either in sw or the hmm
        if failed_queries is not None:
            for failfo in failed_queries:
                assert len(failfo['unique_ids']) == 1
                writer.writerow({'SEQUENCE_ID' : failfo['unique_ids'][0], 'SEQUENCE_INPUT' : failfo['input_seqs'][0]})

# ----------------------------------------------------------------------------------------
def get_airr_cigar_str(line, iseq, region, qr_gap_seq, gl_gap_seq, debug=False):
    if debug:
        if region == 'v':
            print line['unique_ids'][iseq]
        print '  ', region
    istart, istop = line['regional_bounds'][region]
    if indelutils.has_indels(line['indelfos'][iseq]):
        istart += count_gap_chars(qr_gap_seq, unaligned_pos=istart)
        istop += count_gap_chars(qr_gap_seq, unaligned_pos=istop)
    assert len(qr_gap_seq) == len(gl_gap_seq)  # this should be checked in a bunch of other places, but it's nice to see it here
    regional_qr_gap_seq = istart * gap_chars[0] + qr_gap_seq[istart : istop] + (len(qr_gap_seq) - istop) * gap_chars[0]
    regional_gl_gap_seq = istart * gap_chars[0] + gl_gap_seq[istart : istop] + (len(qr_gap_seq) - istop) * gap_chars[0]
    if debug:
        print '      ', regional_qr_gap_seq
        print '      ', regional_gl_gap_seq
    cigarstr = indelutils.get_cigarstr_from_gap_seqs(regional_qr_gap_seq, regional_gl_gap_seq, debug=debug)
    return cigarstr

# ----------------------------------------------------------------------------------------
def get_airr_line(line, iseq, partition=None, debug=False):
    qr_gap_seq = line['seqs'][iseq]
    gl_gap_seq = line['naive_seq']
    if indelutils.has_indels(line['indelfos'][iseq]):
        qr_gap_seq = line['indelfos'][iseq]['qr_gap_seq']
        gl_gap_seq = line['indelfos'][iseq]['gl_gap_seq']

    aline = {}
    for akey, pkey in airr_headers.items():
        if pkey is not None:  # if there's a direct correspondence to a partis key
            aline[akey] = line[pkey][iseq] if pkey in linekeys['per_seq'] else line[pkey]
        elif akey == 'rev_comp':
            aline[akey] = False
        elif '_cigar' in akey and akey[0] in regions:
            aline[akey] = get_airr_cigar_str(line, iseq, akey[0], qr_gap_seq, gl_gap_seq, debug=debug)
        elif akey == 'productive':
            aline[akey] = is_functional(line, iseq)
        elif akey == 'sequence_alignment':
            aline[akey] = qr_gap_seq
        elif akey == 'germline_alignment':
            aline[akey] = gl_gap_seq
        elif akey == 'junction':
            aline[akey] = get_cdr3_seq(line, iseq)
        elif akey == 'junction_aa':
            aline[akey] = ltranslate(aline.get('junction', get_cdr3_seq(line, iseq)))  # should already be in there, since we're using an ordered dict and the previous elif block should've added it
        elif akey == 'clone_id':
            if partition is None:
                continue
            iclusts = [iclust for iclust in range(len(partition)) if line['unique_ids'][iseq] in partition[iclust]]
            if len(iclusts) == 0:
                print '  %s sequence \'%s\' not found in partition' % (color('red', 'warning'), line['unique_ids'][iseq])
                iclusts = [-1]  # uh, sure, that's a good default
            elif len(iclusts) > 1:
                print '  %s sequence \'%s\' occurs multiple times (%d) in partition' % (color('red', 'warning'), line['unique_ids'][iseq], len(iclusts))
            aline[akey] = str(iclusts[0])
        elif akey == 'locus':
            aline[akey] = get_locus(line['v_gene'])
        elif '_support' in akey and akey[0] in regions:  # NOTE not really anywhere to put the alternative annotation, which is independent of this and maybe more accurate
            pkey = akey[0] + '_per_gene_support'
            gcall = line[akey[0] + '_gene']
            if pkey not in line or gcall not in line[pkey]:
                continue
            aline[akey] = line[pkey][gcall]
        elif akey == 'duplicate_count':
            aline[akey] = get_multiplicity(line, iseq=iseq)
        elif '_identity' in akey:
            aline[akey] = 1. - get_mutation_rate(line, iseq, restrict_to_region=akey.split('_')[0])
        elif any(akey == r+'_sequence_start' for r in regions):
            aline[akey] = line['regional_bounds'][akey.split('_')[0]][0] + 1  # +1 to switch to 1-based indexing
        elif any(akey == r+'_sequence_end' for r in regions):
            aline[akey] = line['regional_bounds'][akey.split('_')[0]][1]  # +1 to switch to 1-based indexing, -1 to switch to closed intervals, so net zero
        elif akey == 'cdr3_start':  # airr uses the imgt (correct) cdr3 definition, which excludes both conserved codons, so we add 3 (then add 1 to switch to 1-based indexing)
            aline[akey] = line['codon_positions']['v'] + 3 + 1
        elif akey == 'cdr3_end':
            aline[akey] = line['codon_positions']['j']
        else:
            raise Exception('unhandled airr key / partis key \'%s\' / \'%s\'' % (akey, pkey))

    return aline

# ----------------------------------------------------------------------------------------
def write_airr_output(outfname, annotation_list, cpath, failed_queries, debug=False):  # NOTE similarity to add_regional_alignments() (but I think i don't want to combine them, since add_regional_alignments() is for imgt-gapped aligments, whereas airr format doesn't require imgt gaps, and we really don't want to deal with imgt gaps if we don't need to)
    print '   writing airr annotations to %s' % outfname
    assert getsuffix(outfname) == '.tsv'  # already checked in processargs.py
    with open(outfname, 'w') as outfile:
        writer = csv.DictWriter(outfile, airr_headers.keys(), delimiter='\t')
        writer.writeheader()
        for line in annotation_list:
            for iseq in range(len(line['unique_ids'])):
                aline = get_airr_line(line, iseq, partition=cpath.partitions[cpath.i_best] if cpath is not None else None, debug=debug)
                writer.writerow(aline)

        # and write empty lines for seqs that failed either in sw or the hmm
        if failed_queries is not None:
            for failfo in failed_queries:
                assert len(failfo['unique_ids']) == 1
                writer.writerow({'sequence_id' : failfo['unique_ids'][0], 'sequence' : failfo['input_seqs'][0]})

# ----------------------------------------------------------------------------------------
def process_input_linearham_line(lh_line):
    """ convert <lh_line> (see linearham_headers). Modifies <lh_line>. """
    for lhk in set(lh_line): # set() used because keys are removed from the dict while iterating
        if lhk not in linearham_headers or linearham_headers[lhk] is None: # limit to the ones with a direct partis correspondence
            del lh_line[lhk] #remove keys not in linearham_headers
            continue
        lh_line[linearham_headers[lhk]] = lh_line[lhk]
        del lh_line[lhk] #remove lh_line keys once corresponding linearham_headers key added
    process_input_line(lh_line)

# ----------------------------------------------------------------------------------------
def get_parameter_fname(column=None, deps=None, column_and_deps=None):
    """ return the file name in which we store the information for <column>. Either pass in <column> and <deps> *or* <column_and_deps> """
    if column == 'all':
        return 'all-probs.csv'
    if column_and_deps is None:
        if column is None or deps is None:
            raise Exception('you have to either pass <column_and_deps>, or else pass both <column> and <deps>')
        column_and_deps = [column]
        column_and_deps.extend(deps)
    outfname = 'probs.csv'
    for ic in column_and_deps:
        outfname = ic + '-' + outfname
    return outfname

# ----------------------------------------------------------------------------------------
def from_same_event(reco_info, query_names):  # putting are_clonal in a comment, since that's what I always seem to search for when I'm trying to remember where this fcn is
    if len(query_names) > 1:
        # reco_id = reco_info[query_names[0]]['reco_id']  # the first one's reco id
        # for iq in range(1, len(query_names)):  # then loop through the rest of 'em to see if they're all the same
        #     if reco_id != reco_info[query_names[iq]]['reco_id']:
        #         return False
        # return True

        # darn it, this isn't any faster
        reco_ids = [reco_info[query]['reco_id'] for query in query_names]
        return reco_ids.count(reco_ids[0]) == len(reco_ids)  # they're clonal if every reco id is the same as the first one

    else:  # one or zero sequences
        return True

# ----------------------------------------------------------------------------------------
# bash color codes
Colors = {}
Colors['head'] = '\033[95m'
Colors['bold'] = '\033[1m'
Colors['purple'] = '\033[95m'
Colors['blue'] = '\033[94m'
Colors['light_blue'] = '\033[1;34m'
Colors['green'] = '\033[92m'
Colors['yellow'] = '\033[93m'
Colors['red'] = '\033[91m'
Colors['reverse_video'] = '\033[7m'
Colors['red_bkg'] = '\033[41m'
Colors['end'] = '\033[0m'

def color(col, seq, width=None, padside='left'):
    if col is None:
        return seq
    return_str = [Colors[col], seq, Colors['end']]
    if width is not None:  # make sure final string prints to correct width
        n_spaces = max(0, width - len(seq))  # if specified <width> is greater than uncolored length of <seq>, pad with spaces so that when the colors show up properly the colored sequences prints with width <width>
        if padside == 'left':
            return_str.insert(0, n_spaces * ' ')
        elif padside == 'right':
            return_str.insert(len(return_str), n_spaces * ' ')
        else:
            assert False
    return ''.join(return_str)

def len_excluding_colors(seq):  # NOTE this won't work if you inserted a color code into the middle of another color code
    for color_code in Colors.values():
        seq = seq.replace(color_code, '')
    return len(seq)

def len_only_letters(seq):  # usually the same as len_excluding_colors(), except it doesn't count gap chars or spaces
    return len(filter((alphabet).__contains__, seq))

# ----------------------------------------------------------------------------------------
def color_chars(chars, col, seq):
    if sum([seq.count(c) for c in chars]) == 0:  # if <chars> aren't present, immediately return
        return seq
    return_str = [color(col, c) if c in chars else c for c in seq]
    return ''.join(return_str)

# ----------------------------------------------------------------------------------------
def align_many_seqs(seqfos, outfname=None, existing_aligned_seqfos=None, ignore_extra_ids=False):  # if <outfname> is specified, we just tell mafft to write to <outfname> and then return None
    def outfile_fcn():
        if outfname is None:
            return tempfile.NamedTemporaryFile()
        else:
            return open(outfname, 'w')
    if existing_aligned_seqfos is not None and len(existing_aligned_seqfos) == 0:
        existing_aligned_seqfos = None

    with tempfile.NamedTemporaryFile() as fin, outfile_fcn() as fout:
        for seqfo in seqfos:
            fin.write('>%s\n%s\n' % (seqfo['name'], seqfo['seq']))
        fin.flush()
        if existing_aligned_seqfos is None:  # default: align all the sequences in <seqfos>
            # subprocess.check_call('mafft --quiet %s >%s' % (fin.name, fout.name), shell=True)
            outstr, errstr = simplerun('mafft --quiet %s >%s' % (fin.name, fout.name), shell=True, return_out_err=True, debug=False)
        else:  # if <existing_aligned_seqfos> is set, we instead add the sequences in <seqfos> to the alignment in <existing_aligned_seqfos>
            with tempfile.NamedTemporaryFile() as existing_alignment_file:  # NOTE duplicates code in glutils.get_new_alignments()
                biggest_length = max(len(sfo['seq']) for sfo in existing_aligned_seqfos)
                for sfo in existing_aligned_seqfos:
                    dashstr = '-' * (biggest_length - len(sfo['seq']))
                    existing_alignment_file.write('>%s\n%s\n' % (sfo['name'], sfo['seq'].replace('.', '-') + dashstr))
                existing_alignment_file.flush()
                # subprocess.check_call('mafft --keeplength --add %s %s >%s' % (fin.name, existing_alignment_file.name, fout.name), shell=True)  #  --reorder
                outstr, errstr = simplerun('mafft --keeplength --add %s %s >%s' % (fin.name, existing_alignment_file.name, fout.name), shell=True, return_out_err=True, debug=False)  #  --reorder

        if outfname is not None:
            return None

        msa_info = read_fastx(fout.name, ftype='fa')
        if existing_aligned_seqfos is not None:  # this may not be necessary, but may as well stay as consistent as possible
            for sfo in msa_info:
                sfo.update({'seq' : sfo['seq'].replace('-', '.')})

        input_ids = set([sfo['name'] for sfo in seqfos])
        output_ids = set([sfo['name'] for sfo in msa_info])
        missing_ids = input_ids - output_ids
        extra_ids = output_ids - input_ids
        if len(missing_ids) > 0 or (not ignore_extra_ids and len(extra_ids) > 0):
            print '  %d input ids not in output: %s' % (len(missing_ids), ' '.join(missing_ids))
            print '  %d extra ids in output: %s' % (len(extra_ids), ' '.join(extra_ids))
            print '  mafft out/err:'
            print pad_lines(outstr)
            print pad_lines(errstr)
            raise Exception('error reading mafft output from %s (see previous lines)' % fin.name)

    return msa_info

# ----------------------------------------------------------------------------------------
def align_seqs(ref_seq, seq):  # should eventually change name to align_two_seqs() or something
    with tempfile.NamedTemporaryFile() as fin, tempfile.NamedTemporaryFile() as fout:
        fin.write('>%s\n%s\n' % ('ref', ref_seq))
        fin.write('>%s\n%s\n' % ('new', seq))
        fin.flush()
        subprocess.check_call('mafft --quiet %s >%s' % (fin.name, fout.name), shell=True)
        msa_info = {sfo['name'] : sfo['seq'] for sfo in read_fastx(fout.name, ftype='fa')}
        if 'ref' not in msa_info or 'new' not in msa_info:
            subprocess.check_call(['cat', fin.name])
            raise Exception('incoherent mafft output from %s (cat\'d on previous line)' % fin.name)
    return msa_info['ref'], msa_info['new']

# ----------------------------------------------------------------------------------------
def print_cons_seq_dbg(seqfos, cons_seq, aa=False, align=False, tie_resolver_seq=None, tie_resolver_label=None):
    for iseq in range(len(seqfos)):
        post_ref_str, mstr =  '', ''
        if 'multiplicity' in seqfos[iseq]:
            mstr = '%-3d ' % seqfos[iseq]['multiplicity']
            if seqfos[iseq]['multiplicity'] > 1:
                mstr = color('blue', mstr)
            post_ref_str = color('blue', ' N')
        color_mutants(cons_seq, seqfos[iseq]['seq'], align=align, amino_acid=aa, print_result=True, only_print_seq=iseq>0, ref_label=' consensus ', extra_str='  ', post_str='    %s%s'%(mstr, seqfos[iseq]['name']), post_ref_str=post_ref_str, print_n_snps=True)
    if tie_resolver_seq is not None:
        color_mutants(cons_seq, tie_resolver_seq, align=align, amino_acid=aa, print_result=True, only_print_seq=True, seq_label=' '*len(' consensus '),
                      post_str='    tie resolver%s'%('' if tie_resolver_label is None else (' (%s)'%tie_resolver_label)), extra_str='  ', print_n_snps=True)

# ----------------------------------------------------------------------------------------
def cons_seq(threshold, aligned_seqfos=None, unaligned_seqfos=None, aa=False, tie_resolver_seq=None, tie_resolver_label=None, debug=False):
    """ return consensus sequence from either aligned or unaligned seqfos """
    # <threshold>: If the percentage*0.01 of the most common residue type is greater then the passed threshold, then we will add that residue type, otherwise an ambiguous character will be added. e.g. 0.1 means if fewer than 10% of sequences have the most common base, it gets an N.
    # <tie_resolver_seq>: in case of ties, use the corresponding base from this sequence (for us, this is usually the naive sequence) NOTE if you *don't* set this argument, all tied bases will be Ns
    from cStringIO import StringIO
    from Bio.Align import AlignInfo
    import Bio.AlignIO

    if aligned_seqfos is not None:
        assert unaligned_seqfos is None
        seqfos = aligned_seqfos
    elif unaligned_seqfos is not None:
        assert aligned_seqfos is None
        assert not aa  # not sure if the alignment fcn can handle aa seqs as it is (and i don't need it a.t.m.)
        seqfos = align_many_seqs(unaligned_seqfos)
    else:
        assert False

    def fstr(sfo): return '>%s\n%s' % (sfo['name'], sfo['seq'])
    if 'multiplicity' in seqfos[0]:
        fastalist = [fstr(sfo) for sfo in seqfos for _ in range(sfo['multiplicity'])]
    else:
        fastalist = [fstr(sfo) for sfo in seqfos]
    alignment = Bio.AlignIO.read(StringIO('\n'.join(fastalist) + '\n'), 'fasta')
    cons_seq = str(AlignInfo.SummaryInfo(alignment).gap_consensus(threshold, ambiguous=ambiguous_amino_acids[0] if aa else ambig_base))

    if tie_resolver_seq is not None:  # huh, maybe it'd make more sense to just pass in the tie-breaker sequence to the consensus fcn?
        assert len(tie_resolver_seq) == len(cons_seq)
        cons_seq = list(cons_seq)
        for ipos in range(len(cons_seq)):
            if cons_seq[ipos] in all_ambiguous_bases:
                cons_seq[ipos] = tie_resolver_seq[ipos]
        cons_seq = ''.join(cons_seq)

    if debug:
        print_cons_seq_dbg(seqfos, cons_seq, aa=aa, align=aligned_seqfos is None, tie_resolver_seq=tie_resolver_seq, tie_resolver_label=tie_resolver_label)

    return cons_seq

# ----------------------------------------------------------------------------------------
def seqfos_from_line(line, aa=False):
    tstr = '_aa' if aa else ''
    return [{'name' : u, 'seq' : s, 'multiplicity' : m if m is not None else 1} for u, s, m in zip(line['unique_ids'], line['seqs'+tstr], get_multiplicities(line))]

# ----------------------------------------------------------------------------------------
# NOTE does *not* add either 'consensus_seq' or 'consensus_seq_aa' to <line> (we want that to happen in the calling fcns)
def cons_seq_of_line(line, aa=False, threshold=0.01):  # NOTE unlike general version above, this sets a default threshold (since we mostly want to use it for lb calculations)
    return cons_seq(threshold, aligned_seqfos=seqfos_from_line(line, aa=aa), aa=aa) # NOTE if you turn the naive tie resolver back on, you also probably need to uncomment in treeutils.add_cons_dists(), tie_resolver_seq=line['naive_seq'], tie_resolver_label='naive seq')
# ----------------------------------------------------------------------------------------
    # Leaving the old version below for the moment just for reference.
    # It got the aa cons seq just by translating the nuc one, which is *not* what we want, since it can give you spurious ambiguous bases in the aa cons seq, e.g. if A and C tie at a position (so nuc cons seq has N there), but with either base it still codes for the same aa.
    # if aa:
    #     cseq = line['consensus_seq'] if 'consensus_seq' in line else cons_seq_of_line(line, aa=False, threshold=threshold)  # get the nucleotide cons seq, calculating it if it isn't already there NOTE do *not* use .get(), since in python all function arguments are evaluated *before* the call is excecuted, i.e. it'll call the consensus fcn even if the key is already there
    #     return ltranslate(cseq)
    # else:  # this is fairly slow
    #     aligned_seqfos = [{'name' : u, 'seq' : s, 'multiplicity' : m} for u, s, m in zip(line['unique_ids'], line['seqs'], get_multiplicities(line))]
    #     return cons_seq(threshold, aligned_seqfos=aligned_seqfos) # NOTE if you turn the naive tie resolver back on, you also probably need to uncomment in treeutils.add_cons_dists(), tie_resolver_seq=line['naive_seq'], tie_resolver_label='naive seq')
# ----------------------------------------------------------------------------------------

# ----------------------------------------------------------------------------------------
def get_cons_seq_accuracy_vs_n_sampled_seqs(line, n_sample_min=7, n_sample_step=None, threshold=0.01, debug=False):  # yeah yeah the name is too long, but it's clear, isn't it?
    # NOTE i started to write this so that for small n_sampled it took several different subsamples, but i think that isn't a good idea since we want to make sure they're independent
    def get_step(n_sampled):
        if n_sample_step is not None:  # calling fcn can set it explicitly
            return n_sample_step
        if n_sampled < 10:
            return 1
        elif n_sampled < 20:
            return 3
        elif n_sampled < 30:
            return 4
        elif n_sampled < 40:
            return 5
        elif n_sampled < 85:
            return 10
        else:
            return 30
    def get_n_sample_list(n_total):
        nslist = [n_sample_min]
        while True:
            n_sampled = nslist[-1] + get_step(nslist[-1])
            if n_sampled > n_total:
                break
            nslist.append(n_sampled)
        return nslist

    n_total = len(line['unique_ids'])
    if n_total < n_sample_min:
        if debug:
            print '  small cluster %d' % n_total
        return

    if debug:
        print '  getting cons seq accuracy for cluster with size %d' % n_total
    ctypes = ['nuc', 'aa']
    info = {ct : {'n_sampled' : [], 'cseqs' : [], 'hdists' : None} for ct in ctypes}
    for n_sampled in get_n_sample_list(n_total):
        seqfos = [{'name' : line['unique_ids'][i], 'seq' : line['seqs'][i]} for i in numpy.random.choice(range(n_total), size=n_sampled, replace=False)]
        cseq = cons_seq(threshold, aligned_seqfos=seqfos)  # if we're sampling few enough that ties are frequent, then this doesn't really do what we want (e.g. there's a big oscillation for odd vs even n_sampled, I think because even ones have more ambiguous bases which don't count against them). But it doesn't matter, since ties are only at all frequent for families smaller than we care about (like, less than 10).
        for ctype in ctypes:
            info[ctype]['n_sampled'].append(n_sampled)
        info['nuc']['cseqs'].append(cseq)
        info['aa']['cseqs'].append(ltranslate(cseq))

    for ctype in ctypes:
        best_cseq = info[ctype]['cseqs'][-1]
        info[ctype]['hdists'] = [hamming_distance(cs, best_cseq, amino_acid=ctype=='aa') for cs in info[ctype]['cseqs']]  # it might make more sense for this to use hamming fraction, since small families get perhaps too much credit for ties that end up as ambiguous characters, but whatever
        if debug:
            print '  %s    N sampled   hdist   ' % color('green', ctype, width=6)
            for n_sampled, cseq, hdist in zip(info[ctype]['n_sampled'], info[ctype]['cseqs'], info[ctype]['hdists']):
                print '             %4d      %5.2f     %s' % (n_sampled, hdist, color_mutants(best_cseq, cseq, amino_acid=ctype=='aa'))

    return info

# ----------------------------------------------------------------------------------------
def color_mutants(ref_seq, seq, print_result=False, extra_str='', ref_label='', seq_label='', post_str='', post_ref_str='',
                  print_hfrac=False, print_isnps=False, return_isnps=False, print_n_snps=False, emphasis_positions=None, use_min_len=False,
                  only_print_seq=False, align=False, align_if_necessary=False, return_ref=False, amino_acid=False):  # NOTE if <return_ref> is set, the order isn't the same as the input sequence order
    """ default: return <seq> string with colored mutations with respect to <ref_seq> """

    # NOTE now I've got <return_ref>, I can probably remove a bunch of the label/whatever arguments and do all the damn formatting in the caller

    if use_min_len:
        min_len = min(len(ref_seq), len(seq))
        ref_seq = ref_seq[:min_len]
        seq = seq[:min_len]

    if align or (align_if_necessary and len(ref_seq) != len(seq)):  # it would be nice to avoid aligning when we don't need to... but i'm not sure how to identify cases where multiple indels result in the same length
        ref_seq, seq = align_seqs(ref_seq, seq)

    if len(ref_seq) != len(seq):
        raise Exception('unequal lengths in color_mutants()\n    %s\n    %s' % (ref_seq, seq))

    if amino_acid:
        tmp_ambigs = ambiguous_amino_acids
        tmp_gaps = []
    else:
        tmp_ambigs = all_ambiguous_bases
        tmp_gaps = gap_chars

    return_str, isnps = [], []
    for inuke in range(len(seq)):  # would be nice to integrate this with hamming_distance()
        rchar = ref_seq[inuke]
        char = seq[inuke]
        if char in tmp_ambigs or rchar in tmp_ambigs:
            char = color('blue', char)
        elif char in tmp_gaps or rchar in tmp_gaps:
            char = color('blue', char)
        elif char != rchar:
            char = color('red', char)
            isnps.append(inuke)
        if emphasis_positions is not None and inuke in emphasis_positions:
            char = color('reverse_video', char)
        return_str.append(char)

    isnp_str, n_snp_str = '', ''
    if len(isnps) > 0:
        if print_isnps:
            isnp_str = '   %d snp%s' % (len(isnps), plural(len(isnps)))
            if len(isnps) < 10:
                isnp_str +=  ' at: %s' % ' '.join([str(i) for i in isnps])
    if print_n_snps:
        n_snp_str = ' %3d' % len(isnps)
        if len(isnps) == 0:
            n_snp_str = color('blue', n_snp_str)
    hfrac_str = ''
    if print_hfrac:
        hfrac_str = '   hfrac %.3f' % hamming_fraction(ref_seq, seq)
    if print_result:
        lwidth = max(len_excluding_colors(ref_label), len_excluding_colors(seq_label))
        if not only_print_seq:
            print '%s%s%s%s%s' % (extra_str, ('%' + str(lwidth) + 's') % ref_label, ref_seq, '  hdist' if print_n_snps else '', post_ref_str)
        print '%s%s%s' % (extra_str, ('%' + str(lwidth) + 's') % seq_label, ''.join(return_str) + n_snp_str + post_str + isnp_str + hfrac_str)

    return_list = [extra_str + seq_label + ''.join(return_str) + post_str + isnp_str + hfrac_str]
    if return_ref:
        return_list.append(''.join([ch if ch not in tmp_gaps else color('blue', ch) for ch in ref_seq]))
    if return_isnps:
        return_list.append(isnps)
    return return_list[0] if len(return_list) == 1 else return_list

# ----------------------------------------------------------------------------------------
def plural_str(pstr, count):
    if count == 1:
        return pstr
    else:
        return pstr + 's'

# ----------------------------------------------------------------------------------------
def plural(count, prefix=''):  # I should really combine these
    if count == 1:
        return ''
    else:
        return prefix + 's'

# ----------------------------------------------------------------------------------------
def summarize_gene_name(gene):
    region = get_region(gene)
    primary_version, sub_version, allele = split_gene(gene)
    return ' '.join([region, primary_version, sub_version, allele])

# ----------------------------------------------------------------------------------------
def color_gene(gene, width=None, leftpad=False):
    """ color gene name (and remove extra characters), eg IGHV3-h*01 --> hv3-h1 """
    default_widths = {'v' : 15, 'd' : 9, 'j' : 6}  # wide enough for most genes

    locus = get_locus(gene)
    locus = locus[2]  # hmm... maybe?
    region = get_region(gene)
    primary_version, sub_version, allele = split_gene(gene)

    n_chars = len(locus + region + primary_version)  # number of non-special characters
    return_str = color('purple', locus) + color('red', region) + color('purple', primary_version)
    if sub_version is not None:
        n_chars += 1 + len(sub_version)
        return_str += color('purple', '-' + sub_version)
    n_chars += len(allele)
    return_str += color('yellow', allele)
    if width is not None:
        if width == 'default':
            width = default_widths[region]
        if leftpad:
            return_str = (width - n_chars) * ' ' + return_str
        else:
            return_str += (width - n_chars) * ' '
    return return_str

# ----------------------------------------------------------------------------------------
def color_genes(genelist):  # now that I've added this fcn, I should really go and use this in all the places where the list comprehension is written out
    return ' '.join([color_gene(g) for g in genelist])

#----------------------------------------------------------------------------------------
def int_to_nucleotide(number):
    """ Convert between (0,1,2,3) and (A,C,G,T) """
    if number == 0:
        return 'A'
    elif number == 1:
        return 'C'
    elif number == 2:
        return 'G'
    elif number == 3:
        return 'T'
    else:
        print 'ERROR nucleotide number not in [0,3]'
        sys.exit()

# ----------------------------------------------------------------------------------------
def count_n_separate_gaps(seq, exclusion_5p=None, exclusion_3p=None):  # NOTE compare to count_gap_chars() below (and gap_len() at top)
    if exclusion_5p is not None:
        seq = seq[exclusion_5p : ]
    if exclusion_3p is not None:
        seq = seq[ : len(seq) - exclusion_3p]

    n_gaps = 0
    within_a_gap = False
    for ch in seq:
        if ch not in gap_chars:
            within_a_gap = False
            continue
        elif within_a_gap:
            continue
        within_a_gap = True
        n_gaps += 1

    return n_gaps

# ----------------------------------------------------------------------------------------
def count_gap_chars(aligned_seq, aligned_pos=None, unaligned_pos=None):  # NOTE compare to count_n_separate_gaps() above (and gap_len() at top)
    """ return number of gap characters up to, but not including a position, either in unaligned or aligned sequence """
    if aligned_pos is not None:
        assert unaligned_pos is None
        aligned_seq = aligned_seq[ : aligned_pos]
        return sum([aligned_seq.count(gc) for gc in gap_chars])
    elif unaligned_pos is not None:
        assert aligned_pos is None
        ipos = 0  # position in unaligned sequence
        n_gaps_passed = 0  # number of gapped positions in the aligned sequence that we pass before getting to <unaligned_pos> (i.e. while ipos < unaligned_pos)
        while ipos < unaligned_pos or (ipos + n_gaps_passed < len(aligned_seq) and aligned_seq[ipos + n_gaps_passed] in gap_chars):  # second bit handles alignments with gaps immediately before <unaligned_pos>
            if ipos + n_gaps_passed == len(aligned_seq):  # i.e. <unaligned_pos> is just past the end of the sequence, i.e. slice notation for end of sequence (it would be nice to switch the while to a 'while True' and put all the logic into break statements, but I don't want to change the original stuff a.t.m.
                break
            if aligned_seq[ipos + n_gaps_passed] in gap_chars:
                n_gaps_passed += 1
            else:
                ipos += 1
        return n_gaps_passed
    else:
        assert False

# ----------------------------------------------------------------------------------------
def get_codon_pos_in_alignment(codon, aligned_seq, seq, pos, gene):  # NOTE see gap_len() and accompanying functions above
    """ given <pos> in <seq>, find the codon's position in <aligned_seq> """
    if not codon_unmutated(codon, seq, pos):  # this only gets called on the gene with the *known* position, so it shouldn't fail
        print '  %s mutated %s before alignment in %s' % (color('yellow', 'warning'), codon, gene)
    pos_in_alignment = pos + count_gap_chars(aligned_seq, unaligned_pos=pos)
    if not codon_unmutated(codon, aligned_seq, pos_in_alignment):
        print '  %s mutated %s after alignment in %s' % (color('yellow', 'warning'), codon, gene)
    return pos_in_alignment

# ----------------------------------------------------------------------------------------
def get_pos_in_alignment(aligned_seq, pos):  # kind of annoying to have this as well as get_codon_pos_in_alignment(), but I don't want to change that function's signature NOTE see gap_len() and accompanying functions above
    """ given <pos> in <seq>, find position in <aligned_seq> """
    return pos + count_gap_chars(aligned_seq, unaligned_pos=pos)

# ----------------------------------------------------------------------------------------
def both_codons_unmutated(locus, seq, positions, debug=False, extra_str=''):
    both_ok = True
    for region, codon in conserved_codons[locus].items():
        both_ok &= codon_unmutated(codon, seq, positions[region], debug=debug, extra_str=extra_str)
    return both_ok

# ----------------------------------------------------------------------------------------
def codon_unmutated(codon, seq, position, debug=False, extra_str=''):
    if len(seq) < position + 3:
        if debug:
            print '%ssequence length %d less than %s position %d + 3' % (extra_str, len(seq), codon, position)
        return False
    if seq[position : position + 3] not in codon_table[codon]:  # NOTE this allows it to be mutated to one of the other codons that codes for the same amino acid
        if debug:
            print '%s%s codon %s not among expected codons (%s)' % (extra_str, codon, seq[position : position + 3], ' '.join(codon_table[codon]))
        return False
    return True

#----------------------------------------------------------------------------------------
def in_frame_germline_v(seq, cyst_position):  # NOTE duplication with in_frame() (this is for when all we have is the germline v gene, whereas in_frame() is for when we have the whole rearrangement line)
    return cyst_position <= len(seq) - 3 and (cyst_position - count_gap_chars(seq, aligned_pos=cyst_position)) % 3 == 0

#----------------------------------------------------------------------------------------
def in_frame(seq, codon_positions, fv_insertion, v_5p_del, debug=False):  # NOTE I'm not passing the whole <line> in order to make it more explicit that <seq> and <codon_positions> need to correspond to each other, i.e. are either both for input seqs, or both for indel-reversed seqs
    # NOTE duplication with in_frame_germline_v()
    """ return true if the start and end of the cdr3 are both in frame with respect to the start of the V """
    germline_v_start = len(fv_insertion) - v_5p_del  # position in <seq> (the query sequence) to which the first base of the germline sequence aligns
    v_cpos = codon_positions['v'] - germline_v_start
    j_cpos = codon_positions['j'] - germline_v_start  # NOTE I'm actually not sure how necessary it is that the right side of the J is in frame. I mean, I think it's pretty framework-ey, but I'm not sure.
    if debug:
        print '    in frame:   v codon %d   j codon %d  -->  %s' % (v_cpos % 3 == 0, j_cpos % 3 == 0, v_cpos % 3 == 0 and j_cpos % 3 == 0)
    return v_cpos % 3 == 0 and j_cpos % 3 == 0

#----------------------------------------------------------------------------------------
def is_there_a_stop_codon(seq, fv_insertion, jf_insertion, v_5p_del, debug=False):  # NOTE getting the indexing correct here is extremely non-trivial
    """ true if there's a stop codon in frame with respect to the start of the V """
    germline_v_start = len(fv_insertion) - v_5p_del  # position in <seq> (the query sequence) to which the first base of the germline sequence aligns
    istart = germline_v_start  # start with the first complete codon after <germline_v_start>
    while istart < len(fv_insertion):  # while staying in frame with the start of the v, skootch up to the first base in the query sequence that's actually aligned to the germline (i.e. up to 0 if no fv_insertion, and further if there is one)
        istart += 3
    germline_j_end = len(seq) - len(jf_insertion)  # position immediately after the end of the germline j (if there's a j_3p_del it's accounted for with len(seq))
    istop = germline_j_end - ((germline_j_end - istart) % 3)
    codons = [seq[i : i + 3] for i in range(istart, istop, 3)]
    if debug:
        print '   looking for stop codons: istart %d  istop %d' % (istart, istop)
        print '     seq: %25s' % seq
        print '  codons: %s' % ''.join([color('red' if cdn in codon_table['stop'] else None, cdn) for cdn in codons])
        print '    %d stop codon%s'  % (len(set(codons) & set(codon_table['stop'])), plural(len(set(codons) & set(codon_table['stop']))))
    return len(set(codons) & set(codon_table['stop'])) > 0  # true if any of the stop codons from <codon_table> are present in <codons>

# ----------------------------------------------------------------------------------------
def disambiguate_effective_insertions(bound, line, iseq, debug=False):
    # These are kinda weird names, but the distinction is important
    # If an insert state with "germline" N emits one of [ACGT], then the hmm will report this as an inserted N. Which is what we want -- we view this as a germline N which "mutated" to [ACGT].
    # This concept of insertion germline state is mostly relevant for simultaneous inference on several sequences, i.e. in ham we don't want to just say the inserted base was the base in the query sequence.
    # But here, we're trimming off the effective insertions and we have to treat the inserted germline N to [ACGT] differently than we would an insertion which was "germline" [ACGT] which emitted an N,
    # and also differently to a real germline [VDJ] state that emitted an N.
    naive_insertion = line[bound + '_insertion']  # reminder: ham gets this from the last character in the insertion state name, e.g. 'insert_left_A' or 'insert_right_N'
    insert_len = len(line[bound + '_insertion'])
    if bound == 'fv':  # ...but to accomodate multiple sequences, the insert states can emit non-germline states, so the mature bases might be different.
        mature_insertion = line['seqs'][iseq][ : insert_len]
    elif bound == 'jf':
        mature_insertion = line['seqs'][iseq][len(line['seqs'][iseq]) - insert_len : ]
    else:
        assert False

    if naive_insertion == mature_insertion:  # all is simple and hunky-dory: no insertion 'mutations'
        final_insertion = ''  # leave this bit as an insertion in the final <line>
        insertion_to_remove = naive_insertion  # this bit we'll remove -- it's just Ns (note that this is only equal to the N padding if we correctly inferred the right edge of the J [for jf bound])
    else:
        if len(naive_insertion) != len(mature_insertion):
            raise Exception('naive and mature insertions not the same length\n   %s\n   %s\n' % (naive_insertion, mature_insertion))
        assert naive_insertion.count('N') == len(naive_insertion)  # should be e.g. naive: NNN   mature: ANN
        if bound == 'fv':  # ...but to accomodate multiple sequences, the insert states can emit non-germline states, so the mature bases might be different.
            i_first_non_N = find_first_non_ambiguous_base(mature_insertion)
            final_insertion = mature_insertion[i_first_non_N : ]
            insertion_to_remove = mature_insertion[ : i_first_non_N]
        elif bound == 'jf':
            i_first_N = find_last_non_ambiguous_base_plus_one(mature_insertion)
            final_insertion = mature_insertion[ : i_first_N]
            insertion_to_remove = mature_insertion[i_first_N : ]
        else:
            assert False

    if debug:
        print '     %s      final: %s' % (color('red', bound), color('purple', final_insertion))
        print '         to_remove: %s' % color('blue', insertion_to_remove)

    return final_insertion, insertion_to_remove

# ----------------------------------------------------------------------------------------
# modify <line> so it has no 'fwk' insertions to left of v or right of j
def trim_fwk_insertions(glfo, line, modify_alternative_annotations=False, debug=False):  # NOTE this is *different* to reset_effective_erosions_and_effective_insertions() (i think kind of, but not entirely, the opposite?)
    # NOTE duplicates code in waterer.remove_framework_insertions(), and should really be combined with that fcn
    fv_len = len(line['fv_insertion'])
    jf_len = len(line['jf_insertion'])
    if debug:
        print 'trimming fwk insertions: fv %d  jv %d' % (fv_len, jf_len)
        print_reco_event(line, label='before trimming:', extra_str='    ')

    if fv_len == 0 and jf_len == 0:
        return

    remove_all_implicit_info(line)

    for seqkey in ['seqs', 'input_seqs']:
        line[seqkey] = [seq[fv_len : len(seq) - jf_len] for i, seq in enumerate(line[seqkey])]
    for iseq in range(len(line['unique_ids'])):
        if indelutils.has_indels(line['indelfos'][iseq]):
            indelutils.trim_indel_info(line, iseq, line['fv_insertion'], line['jf_insertion'], 0, 0)
    line['fv_insertion'] = ''
    line['jf_insertion'] = ''

    if modify_alternative_annotations and 'alternative-annotations' in line:  # in principle it'd be nice to also generate these alternative naive seqs when we re-add implicit info, but we don't keep around near enough information to be able to do that
        for iseq, (seq, prob) in enumerate(line['alternative-annotations']['naive-seqs']):
            line['alternative-annotations']['naive-seqs'][iseq] = [seq[fv_len : len(seq) - jf_len], prob]

    add_implicit_info(glfo, line)

    if debug:
        print_reco_event(line, label='after trimming:', extra_str='    ')

# ----------------------------------------------------------------------------------------
def reset_effective_erosions_and_effective_insertions(glfo, padded_line, aligned_gl_seqs=None, debug=False):  # , padfo=None
    """
    Ham does not allow (well, no longer allows) v_5p and j_3p deletions -- we instead pad sequences with Ns.
    This means that the info we get from ham always has these effective erosions set to zero, but for downstream
    things we sometimes want to know where the reads stopped (e.g. if we want to mimic them in simulation).
    Note that these effective erosion values will be present in the parameter dir, but are *not* incorporated into
    the hmm yaml files.
    """

    if debug:
        print 'resetting effective erosions/insertions for %s' % ' '.join(padded_line['unique_ids'])

    line = {k : copy.deepcopy(padded_line[k]) for k in padded_line if k not in implicit_linekeys}

    assert line['v_5p_del'] == 0  # just to be safe
    assert line['j_3p_del'] == 0
    nseqs = len(line['unique_ids'])  # convenience

    # first disambiguate/remove effective (fv and jf) insertions
    if debug:
        print '   disambiguating effective insertions'
    trimmed_seqs = [line['seqs'][iseq] for iseq in range(nseqs)]
    trimmed_input_seqs = [line['input_seqs'][iseq] for iseq in range(nseqs)]
    final_insertions = [{} for _ in range(nseqs)]  # the effective insertions that will remain in the final info
    insertions_to_remove = [{} for _ in range(nseqs)]  # the effective insertions that we'll be removing, so which won't be in the final info
    for iseq in range(nseqs):
        fin = final_insertions[iseq]
        rem = insertions_to_remove[iseq]
        for bound in effective_boundaries:
            final_insertion, insertion_to_remove = disambiguate_effective_insertions(bound, line, iseq, debug=debug)
            fin[bound] = final_insertion
            rem[bound] = insertion_to_remove
        trimmed_seqs[iseq] = trimmed_seqs[iseq][len(rem['fv']) : len(trimmed_seqs[iseq]) - len(rem['jf'])]
        trimmed_input_seqs[iseq] = trimmed_input_seqs[iseq][len(rem['fv']) : len(trimmed_input_seqs[iseq]) - len(rem['jf'])]
        if debug:
            print '       %s  %s%s%s%s%s' % (' '.join(line['unique_ids']),
                                             color('blue', rem['fv']), color('purple', fin['fv']),
                                             trimmed_seqs[iseq][len(fin['fv']) : len(trimmed_seqs[iseq]) - len(fin['jf'])],
                                             color('purple', fin['jf']), color('blue', rem['jf']))

    # arbitrarily use the zeroth sequence (in principle v_5p and j_3p should be per-sequence, not per-rearrangement... but that'd be a mess to implement, since the other deletions are per-rearrangement)
    TMPiseq = 0  # NOTE this is pretty hackey: we just use the values from the first sequence. But it's actually not that bad -- we can either have some extra pad Ns showing, or chop off some bases.
    trimmed_seq = trimmed_seqs[TMPiseq]
    final_fv_insertion = final_insertions[TMPiseq]['fv']
    final_jf_insertion = final_insertions[TMPiseq]['jf']
    fv_insertion_to_remove = insertions_to_remove[TMPiseq]['fv']
    jf_insertion_to_remove = insertions_to_remove[TMPiseq]['jf']

    def max_effective_erosion(erosion):  # don't "erode" more than there is left to erode
        region = erosion[0]
        gl_len = len(glfo['seqs'][region][line[region + '_gene']])
        if '5p' in erosion:
            other_del = line[region + '_3p_del']
        elif '3p' in erosion:
            other_del = line[region + '_5p_del']
        return gl_len - other_del - 1

    line['v_5p_del'] = min(max_effective_erosion('v_5p'), find_first_non_ambiguous_base(trimmed_seq))
    line['j_3p_del'] = min(max_effective_erosion('j_3p'), len(trimmed_seq) - find_last_non_ambiguous_base_plus_one(trimmed_seq))

    if debug:
        v_5p = line['v_5p_del']
        j_3p = line['j_3p_del']
        print '     %s:  %d' % (color('red', 'v_5p'), v_5p)
        print '     %s:  %d' % (color('red', 'j_3p'), j_3p)
        for iseq in range(nseqs):
            print '       %s  %s%s%s' % (' '.join(line['unique_ids']), color('red', v_5p * '.'), trimmed_seqs[iseq][v_5p : len(trimmed_seqs[iseq]) - j_3p], color('red', j_3p * '.'))

    for iseq in range(nseqs):
        line['seqs'][iseq] = trimmed_seqs[iseq][line['v_5p_del'] : len(trimmed_seqs[iseq]) - line['j_3p_del']]
        line['input_seqs'][iseq] = trimmed_input_seqs[iseq][line['v_5p_del'] : len(trimmed_input_seqs[iseq]) - line['j_3p_del']]
        if indelutils.has_indels(line['indelfos'][iseq]):
            indelutils.trim_indel_info(line, iseq, fv_insertion_to_remove, jf_insertion_to_remove, line['v_5p_del'], line['j_3p_del'])

    line['fv_insertion'] = final_fv_insertion
    line['jf_insertion'] = final_jf_insertion

    # if padfo is None:
    #     line['padlefts'], line['padrights'] = [0 for _ in range(len(line['seqs']))], [0 for _ in range(len(line['seqs']))]
    # else:
    #     line['padlefts'], line['padrights'] = [padfo[uid]['padded']['padleft'] for uid in line['unique_ids']], [padfo[uid]['padded']['padright'] for uid in line['unique_ids']]

    # NOTE fixed the problem we were actually seeing, so this shouldn't fail any more, but I'll leave it in for a bit just in case UPDATE totally saved my ass from an unrelated problem (well, maybe not "saved" -- definitely don't remove the add_implicit_info() call though)
    try:
        add_implicit_info(glfo, line, aligned_gl_seqs=aligned_gl_seqs)
    except:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
        print pad_lines(''.join(lines))
        print '  failed adding implicit info to \'%s\' (see above)' % ':'.join(line['unique_ids'])
        line['invalid'] = True

    return line

# ----------------------------------------------------------------------------------------
def add_qr_seqs(line):
    """ Add [vdj]_qr_seq, i.e. the sections of the query sequence which are assigned to each region. """

    starts = {}
    starts['v'] = len(line['fv_insertion'])
    starts['d'] = starts['v'] + len(line['v_gl_seq']) + len(line['vd_insertion'])
    starts['j'] = starts['d'] + len(line['d_gl_seq']) + len(line['dj_insertion'])

    def get_single_qr_seq(region, seq):
        return seq[starts[region] : starts[region] + len(line[region + '_gl_seq'])]

    for region in regions:
        line[region + '_qr_seqs'] = [get_single_qr_seq(region, seq) for seq in line['seqs']]

# ----------------------------------------------------------------------------------------
def is_functional_dbg_str(line, iseq):  # NOTE code duplication with is_functional(
    dbg_str_list = []
    if line['mutated_invariants'][iseq]:
        dbg_str_list.append('mutated invariant codon')
    if not line['in_frames'][iseq]:
        dbg_str_list.append('out of frame cdr3')
    if line['stops'][iseq]:
        dbg_str_list.append('stop codon')
    return ', '.join(dbg_str_list)

# ----------------------------------------------------------------------------------------
def is_functional(line, iseq):  # NOTE code duplication with is_functional_dbg_str(
    if line['mutated_invariants'][iseq]:
        return False
    if not line['in_frames'][iseq]:
        return False
    if line['stops'][iseq]:
        return False
    return True

# ----------------------------------------------------------------------------------------
def add_functional_info(locus, line, input_codon_positions):
    nseqs = len(line['seqs'])  # would normally use 'unique_ids', but this gets called during simulation before the point at which we choose the uids
    line['mutated_invariants'] = [not both_codons_unmutated(locus, line['input_seqs'][iseq], input_codon_positions[iseq])
                                  for iseq in range(nseqs)]
    line['in_frames'] = [in_frame(line['input_seqs'][iseq], input_codon_positions[iseq], line['fv_insertion'], line['v_5p_del'])
                         for iseq in range(nseqs)]
    line['stops'] = [is_there_a_stop_codon(line['input_seqs'][iseq], line['fv_insertion'], line['jf_insertion'], line['v_5p_del'])
                     for iseq in range(nseqs)]

# ----------------------------------------------------------------------------------------
def remove_all_implicit_info(line):
    for col in implicit_linekeys:
        if col in line:
            del line[col]

# ----------------------------------------------------------------------------------------
def get_non_implicit_copy(line):  # return a deep copy of <line> with only non-implicit info
    return {col : copy.deepcopy(line[col]) for col in line if col not in implicit_linekeys}

# ----------------------------------------------------------------------------------------
def process_per_gene_support(line, debug=False):
    for region in regions:
        if debug:
            print region
        support = OrderedDict()
        logtotal = float('-inf')
        for gene, logprob in line[region + '_per_gene_support'].items():
            support[gene] = logprob
            logtotal = add_in_log_space(logtotal, logprob)

        for gene in support:
            if debug:
                print '   %5.2f     %5.2f   %s' % (support[gene], math.exp(support[gene] - logtotal), color_gene(gene))
            support[gene] = math.exp(support[gene] - logtotal)

        if len(support.keys()) > 0 and support.keys()[0] != line[region + '_gene']:
            print '   %s best-supported gene %s not same as viterbi gene %s' % (color('yellow', 'warning'), color_gene(support.keys()[0]), color_gene(line[region + '_gene']))

        line[region + '_per_gene_support'] = support

# ----------------------------------------------------------------------------------------
def re_sort_per_gene_support(line):
    for region in [r for r in regions if r + '_per_gene_support' in line]:
        if type(line[region + '_per_gene_support']) == type(collections.OrderedDict()):  # already ordered, don't need to do anything
            continue
        elif type(line[region + '_per_gene_support']) == types.DictType:  # plain dict, i.e. we just read it from a json.dump()'d file
            line[region + '_per_gene_support'] = collections.OrderedDict(sorted(line[region + '_per_gene_support'].items(), key=operator.itemgetter(1), reverse=True))

# ----------------------------------------------------------------------------------------
def get_null_linearham_info():
    return {'flexbounds' : None, 'relpos' : None}

# ----------------------------------------------------------------------------------------
def add_linearham_info(sw_info, annotation_list, min_cluster_size=None, debug=False):
    n_already_there = 0
    for line in annotation_list:
        if min_cluster_size is not None and len(line['unique_ids']) < min_cluster_size:
            print '       %s adding null linearham info to line: %s, because cluster is less than the passed <min_cluster_size> value of %d' % (color('yellow', 'warning'), ':'.join(line['unique_ids']), min_cluster_size)
            line['linearham-info'] = get_null_linearham_info()
            continue
        if 'linearham-info' in line:
            if debug:
                print '       %s overwriting linearham info that was already in line: %s' % (color('yellow', 'warning'), ':'.join(line['unique_ids']))
            n_already_there += 1
        line['linearham-info'] = get_linearham_bounds(sw_info, line, debug=debug)  # note that we don't skip ones that fail, since we don't want to just silently ignore some of the input sequences -- skipping should happen elsewhere where it can be more explicit
    if n_already_there > 0:
        print '    %s overwriting %d / %d that already had linearham info' % (color('yellow', 'warning'), n_already_there, len(annotation_list))
    if len(annotation_list) > n_already_there:
        print '    added new linearham info for %d clusters' % (len(annotation_list) - n_already_there)

# ----------------------------------------------------------------------------------------
def get_linearham_bounds(sw_info, line, vj_flexbounds_shift=10, debug=False):
    """ compute the flexbounds/relpos values and return in a dict """  # NOTE deep copies per_gene_support, and then modifies this copy
    def get_swfo(uid):
        def getmatches(matchfo):  # get list of gene matches sorted by decreasing score
            genes, gfos = zip(*sorted(matchfo.items(), key=lambda x: x[1]['score'], reverse=True))
            return genes
        swfo = {'flexbounds' : {}, 'relpos' : {}}
        for region in getregions(get_locus(line['v_gene'])):
            matchfo = sw_info[uid]['all_matches'][0][region]
            if isinstance(matchfo, list):
                raise Exception('\'all_matches\' key in sw info doesn\'t have qr/gl bound information, so can\'t add linearham info (it\'s probably an old sw cache file from before we started storing this info -- re-cache-parameters to rewrite it)')
            sortmatches = getmatches(matchfo)
            bounds_l, bounds_r = zip(*[matchfo[g]['qrbounds'] for g in sortmatches])  # left- (and right-) bounds for each gene
            swfo['flexbounds'][region + '_l'] = dict(zip(sortmatches, bounds_l))
            swfo['flexbounds'][region + '_r'] = dict(zip(sortmatches, bounds_r))
            for gene, gfo in matchfo.items():
                swfo['relpos'][gene] = gfo['qrbounds'][0] - gfo['glbounds'][0]  # position in the query sequence of the start of each uneroded germline match
        return swfo

    fbounds = {}  # initialize the flexbounds/relpos dicts
    rpos = {}

    for region in getregions(get_locus(line['v_gene'])):
        left_region, right_region = region + '_l', region + '_r'
        fbounds[left_region] = {}
        fbounds[right_region] = {}

    # rank the query sequences according to their consensus sequence distances
    cons_seq = ''.join([Counter(site_bases).most_common()[0][0] for site_bases in zip(*line['seqs'])])
    dists_to_cons = {line['unique_ids'][i] : hamming_distance(cons_seq, line['seqs'][i]) for i in range(len(line['unique_ids']))}

    # loop over the ranked query sequences and update the flexbounds/relpos dicts
    while len(dists_to_cons) > 0:
        query_name = min(dists_to_cons, key=dists_to_cons.get)
        swfo = get_swfo(query_name)

        for region in getregions(get_locus(line['v_gene'])):
            left_region, right_region = region + '_l', region + '_r'
            fbounds[left_region] = dict(swfo['flexbounds'][left_region].items() + fbounds[left_region].items())
            fbounds[right_region] = dict(swfo['flexbounds'][right_region].items() + fbounds[right_region].items())
        rpos = dict(swfo['relpos'].items() + rpos.items())

        del dists_to_cons[query_name]

    # 1) restrict flexbounds/relpos to gene matches with non-zero support
    # 2) if the left/right flexbounds overlap in a particular region, remove the worst gene matches until the overlap disappears
    # 3) if neighboring flexbounds overlap across different regions, apportion the flexbounds until the overlap disappears
    # 4) if possible, widen the gap between neighboring flexbounds
    # 5) align the V-entry/J-exit flexbounds to the sequence bounds

    def are_fbounds_empty(fbounds, region, gene_removed, reason_removed):
        left_region, right_region = region + '_l', region + '_r'
        if len(fbounds[left_region].values()) == 0 or len(fbounds[right_region].values()) == 0:
            print '{}: removed all genes from flexbounds for region {}: {}. The last gene removed was {}. It was removed because {}. Returning null linearham info'.format(color('yellow', 'warning'), region, fbounds, gene_removed, reason_removed)
            return True
        return False

    def span(bound_list):
        return [min(bound_list), max(bound_list)]

    for region in getregions(get_locus(line['v_gene'])):
        # EH: remember when reading this that left_region and right_region are not one of (v,d,j) as variables named like *region* often are in partis. Here they have _l or _r on the end so they are a particlar end of a region
        left_region, right_region = region + '_l', region + '_r'
        per_gene_support = copy.deepcopy(line[region + '_per_gene_support'])
        # remove the gene matches with zero support
        for k in fbounds[left_region].keys():
            support_check1 = (k not in per_gene_support)
            support_check2 = (math.fabs(per_gene_support[k] - 0.0) < eps) if not support_check1 else False
            if support_check1 or support_check2:
                del fbounds[left_region][k]
                del fbounds[right_region][k]
                del rpos[k]
                if debug:
                    print 'removing %s from fbounds (and per_gene_support if it was there to begin with) for region %s because it was not in per_gene_support or had too low support.' % (k, region)
                if support_check2:
                    del per_gene_support[k]
            if are_fbounds_empty(fbounds, region, k, '{} was not in per_gene_support or had too low support'.format(k)):
                return get_null_linearham_info()

        # compute the initial left/right flexbounds
        left_flexbounds = span(fbounds[left_region].values())
        right_flexbounds = span(fbounds[right_region].values())
        germ_len = right_flexbounds[0] - left_flexbounds[1]
        # make sure there is no overlap between the left/right flexbounds
        while germ_len < 1:
            k = min(per_gene_support, key=per_gene_support.get)
            del fbounds[left_region][k]
            del fbounds[right_region][k]
            del rpos[k]
            del per_gene_support[k]
            if debug:
                print 'removing %s from fbounds and perg_gene_support to resolve a supposed overlap berween left and right flexbounds for region %s' % (k, region)
            # check removing all items from fbounds 
            if are_fbounds_empty(fbounds, region, k, 'right flexbounds was less than left for {}'.format(region)):
                return get_null_linearham_info()
            left_flexbounds = span(fbounds[left_region].values())
            right_flexbounds = span(fbounds[right_region].values())
            germ_len = right_flexbounds[0] - left_flexbounds[1]
        fbounds[left_region] = left_flexbounds
        fbounds[right_region] = right_flexbounds

    # make sure there is no overlap between neighboring flexbounds
    # maybe widen the gap between neighboring flexbounds
    for rpair in region_pairs(get_locus(line['v_gene'])):
        # EH: remember when reading this that left_region and right_region are not one of (v,d,j) as variables named like *region* often are in partis. Here they have _l or _r on the end so they are a particlar end of a region
        left_region, right_region = rpair['left'] + '_r', rpair['right'] + '_l'
        leftleft_region, rightright_region = rpair['left'] + '_l', rpair['right'] + '_r'

        left_germ_len = fbounds[left_region][0] - fbounds[leftleft_region][1]
        junction_len = fbounds[right_region][1] - fbounds[left_region][0]
        right_germ_len = fbounds[rightright_region][0] - fbounds[right_region][1]

        if junction_len < 1:
            if debug:
                print '''
                          Overlap resolution code running in partis utils.get_linearham_bounds.
                          Post Duncan's fix to ig-sw (see *), we really should not have a true overlap of neighboring matches.
                          So ideally this code would not ever get triggered. However, this code does get triggered if there
                          are adjacent matches which share regional bounds, which is possible because partis uses python slice
                          conventions for regional bounds (so this is not a "real" overlap).
                          E.g. if fbounds[left_region] = [x,x] and fbounds[right_region] = [x,x] as well,
                          this code gets executed despite this not being a true overlap.
                          However in such a case this code does nothing so we are not changing it for fear of messing up the logic here.
                          *: https://github.com/psathyrella/partis/commit/471e5eac6d2b0fbdbb2b6024c81af14cdc3d9399
                      '''
            fbounds[left_region][0] = fbounds[right_region][0]
            fbounds[right_region][1] = fbounds[left_region][1]

            left_germ_len = fbounds[left_region][0] - fbounds[leftleft_region][1]
            junction_len = fbounds[right_region][1] - fbounds[left_region][0]
            right_germ_len = fbounds[rightright_region][0] - fbounds[right_region][1]

            # are the neighboring flexbounds even fixable?
            if left_germ_len < 1 or right_germ_len < 1:
                print '    failed adding linearham info for line %s due to overlapping neighboring fbounds between %s and %s' % (':'.join(line['unique_ids']), left_region, right_region)
                return get_null_linearham_info()

        # EH: This section corresponds to step #4 in the comment earlier in this fcn. Note that both the lower and upper bounds are shifted away from their neighboring gene in all cases here. This might seem odd, since performing such a shift on just one bound might help account for more uncertainty at the junction of each pair of genes, but shifting both bounds in the same direction wouldn't appear to have that effect. However, because linearham only cares about the bound furthest from the neighboring gene when considering a junction between two genes, the end result of shifting both bounds in this logic here is the same as if we had just shifted one bound in each gene (linearham's bound of interest for the gene) and the desired effect of the shift is achieved, i.e. that we just allow for some extra flexibility/uncertainty in these junction regions.
        if rpair['left'] == 'v' and left_germ_len > vj_flexbounds_shift:
            if debug:
                print 'shifting lower and uppper fbounds for %s by %d' % (left_region, vj_flexbounds_shift)
            fbounds[left_region][0] -= vj_flexbounds_shift
            fbounds[left_region][1] -= vj_flexbounds_shift

        # the D gene match region is constrained to have a length of 1
        if rpair['left'] == 'd':
            if debug:
                print 'shifting lower and uppper fbounds for %s by %d' % (left_region, left_germ_len - 1)
            fbounds[left_region][0] -= (left_germ_len - 1)
            fbounds[left_region][1] -= (left_germ_len - 1)
        if rpair['right'] == 'd':
            if debug:
                print 'shifting lower and uppper fbounds for %s by %d' % (right_region, right_germ_len / 2)
            fbounds[right_region][0] += (right_germ_len / 2)
            fbounds[right_region][1] += (right_germ_len / 2)

        if rpair['right'] == 'j' and right_germ_len > vj_flexbounds_shift:
            if debug:
                print 'shifting lower and uppper fbounds for %s by %d' % (right_region, vj_flexbounds_shift)
            fbounds[right_region][0] += vj_flexbounds_shift
            fbounds[right_region][1] += vj_flexbounds_shift

    # align the V-entry/J-exit flexbounds to the possible sequence positions
    fbounds['v_l'][0] = 0
    fbounds['j_r'][1] = len(line['seqs'][0])  # remember indel-reversed sequences are all the same length

    # are the V-entry/J-exit flexbounds valid?
    for region in ['v_l', 'j_r']:
        bounds_len = fbounds[region][1] - fbounds[region][0]
        if bounds_len < 0:
            print '    failed adding linearham info for line: %s . fbounds is negative length for region %s' % (':'.join(line['unique_ids']), region)
            return get_null_linearham_info()

    return {'flexbounds' : fbounds, 'relpos' : rpos}

# ----------------------------------------------------------------------------------------
def add_implicit_info(glfo, line, aligned_gl_seqs=None, check_line_keys=False, reset_indel_genes=False):  # should turn on <check_line_keys> for a bit if you change anything
    """ Add to <line> a bunch of things that are initially only implicit. """
    if line['v_gene'] == '':
        raise Exception('can\'t add implicit info to line with failed annotation:\n%s' % (''.join(['  %+20s  %s\n' % (k, v) for k, v in line.items()])))

    if check_line_keys:
        initial_keys = set(line)
        # first make sure there aren't any unauthorized keys
        if len(initial_keys - all_linekeys) > 0:
            raise Exception('unexpected keys: \'%s\'' % '\' \''.join(initial_keys - all_linekeys))
        # then keep track of the keys we got to start with
        pre_existing_implicit_info = {ek : copy.deepcopy(line[ek]) for ek in implicit_linekeys if ek in line}

    for region in regions:  # backwards compatibility with old simulation files should be removed when you're no longer running on them
        if line[region + '_gene'] not in glfo['seqs'][region]:
            alternate_name = glutils.convert_to_duplicate_name(glfo, line[region + '_gene'])
            # print ' using alternate name %s instead of %s' % (alternate_name, line[region + '_gene'])
            line[region + '_gene'] = alternate_name

    # add the regional germline seqs and their lengths
    line['lengths'] = {}  # length of each match (including erosion)
    for region in regions:
        uneroded_gl_seq = glfo['seqs'][region][line[region + '_gene']]
        del_5p = line[region + '_5p_del']
        del_3p = line[region + '_3p_del']
        length = len(uneroded_gl_seq) - del_5p - del_3p  # eroded length
        if length < 0:
            raise Exception('invalid %s lengths passed to add_implicit_info()\n    gl seq: %d  5p: %d  3p: %d' % (region, len(uneroded_gl_seq), del_5p, del_3p))
        line[region + '_gl_seq'] = uneroded_gl_seq[del_5p : del_5p + length]
        line['lengths'][region] = length

    # add codon-related stuff
    line['codon_positions'] = {}
    for region, codon in conserved_codons[glfo['locus']].items():
        eroded_gl_pos = glfo[codon + '-positions'][line[region + '_gene']] - line[region + '_5p_del']
        if region == 'v':
            line['codon_positions'][region] = eroded_gl_pos + len(line['f' + region + '_insertion'])
        elif region == 'j':
            line['codon_positions'][region] = eroded_gl_pos + len(line['fv_insertion']) + line['lengths']['v'] + len(line['vd_insertion']) + line['lengths']['d'] + len(line['dj_insertion'])
        else:
            assert False
    line['cdr3_length'] = line['codon_positions']['j'] - line['codon_positions']['v'] + 3  # i.e. first base of cysteine to last base of tryptophan inclusive

    # add naive seq stuff
    line['naive_seq'] = len(line['fv_insertion']) * ambig_base + line['v_gl_seq'] + line['vd_insertion'] + line['d_gl_seq'] + line['dj_insertion'] + line['j_gl_seq'] + len(line['jf_insertion']) * ambig_base
    for iseq in range(len(line['seqs'])):
        if len(line['naive_seq']) != len(line['seqs'][iseq]):
            raise Exception('naive and mature sequences different lengths %d %d for %d-seq annotation %s:\n    %s\n    %s' % (len(line['naive_seq']), len(line['seqs'][iseq]), len(line['unique_ids']), ':'.join(line['unique_ids']), line['naive_seq'], line['seqs'][iseq]))

    start, end = {}, {}  # add naive seq bounds for each region (could stand to make this more concise)
    start['v'] = len(line['fv_insertion'])  # NOTE this duplicates code in add_qr_seqs()
    end['v'] = start['v'] + len(line['v_gl_seq'])  # base just after the end of v
    start['d'] = end['v'] + len(line['vd_insertion'])
    end['d'] = start['d'] + len(line['d_gl_seq'])
    start['j'] = end['d'] + len(line['dj_insertion'])
    end['j'] = start['j'] + len(line['j_gl_seq'])
    line['regional_bounds'] = {r : (start[r], end[r]) for r in regions}

    try:
        indelutils.deal_with_indel_stuff(line, reset_indel_genes=reset_indel_genes)
    except indelutils.IndelfoReconstructionError:  # I don't like this here, but see note in the one place it can be raised
        line['invalid'] = True
        return

    input_codon_positions = [indelutils.get_codon_positions_with_indels_reinstated(line, iseq, line['codon_positions']) for iseq in range(len(line['seqs']))]
    if 'indel_reversed_seqs' not in line:  # everywhere internally, we refer to 'indel_reversed_seqs' as simply 'seqs'. For interaction with outside entities, however (i.e. writing files) we use the more explicit 'indel_reversed_seqs'
        line['indel_reversed_seqs'] = line['seqs']

    # add regional query seqs
    add_qr_seqs(line)

    add_functional_info(glfo['locus'], line, input_codon_positions)

    hfracfo = [hamming_fraction(line['naive_seq'], mature_seq, also_return_distance=True) for mature_seq in line['seqs']]
    line['mut_freqs'] = [hfrac for hfrac, _ in hfracfo]
    line['n_mutations'] = [n_mutations for _, n_mutations in hfracfo]

    # set validity (alignment addition [below] can also set invalid)  # it would be nice to clean up this checking stuff
    line['invalid'] = False
    seq_length = len(line['seqs'][0])  # they shouldn't be able to be different lengths
    for chkreg in regions:
        if start[chkreg] < 0 or end[chkreg] < 0 or end[chkreg] < start[chkreg] or end[chkreg] > seq_length:
            line['invalid'] = True
    if end['j'] + len(line['jf_insertion']) != seq_length:
        line['invalid'] = True
    if line['cdr3_length'] < 6:  # i.e. if cyst and tryp overlap  NOTE six is also hardcoded in waterer
        line['invalid'] = True

    # add alignment info (this is only used if presto output has been specified on the command line, which requires specification of your own alignment file)
    if aligned_gl_seqs is None:  # empty/dummy info
        for region in regions:
            line['aligned_' + region + '_seqs'] = ['' for _ in range(len(line['seqs']))]
    else:
        add_alignments(glfo, aligned_gl_seqs, line)

    re_sort_per_gene_support(line)  # in case it was read from json.dump()'d file

    if check_line_keys:
        new_keys = set(line) - initial_keys
        if len(new_keys - implicit_linekeys) > 0:
            raise Exception('added new keys that aren\'t in implicit_linekeys: %s' % ' '.join(new_keys - implicit_linekeys))
        for ikey in implicit_linekeys:  # make sure every key/value we added is either a) new or b) the same as it was before
            if ikey in initial_keys:
                if pre_existing_implicit_info[ikey] != line[ikey]:
                    print '%s pre-existing info for \'%s\' in %s\n    %s\n    doesn\'t match new info\n    %s' % (color('yellow', 'warning'), ikey, line['unique_ids'], pre_existing_implicit_info[ikey], line[ikey])
            else:
                assert ikey in new_keys  # only really checks the logic of the previous few lines

# ----------------------------------------------------------------------------------------
def restrict_to_iseqs(line, iseqs_to_keep, glfo, sw_info=None):  # could have called it subset_seqs_in_line, or at least i always seem to search for that when i'm trying to find this
    """ remove from <line> any sequences corresponding to indices not in <iseqs_to_keep>. modifies line. """
    if len(iseqs_to_keep) < 1:
        raise Exception('must be called with at least one sequence to keep (got %s)' % iseqs_to_keep)
    remove_all_implicit_info(line)
    for tkey in set(linekeys['per_seq']) & set(line):
        line[tkey] = [line[tkey][iseq] for iseq in iseqs_to_keep]
    add_implicit_info(glfo, line)
    if line.get('linearham-info') is not None:
        if sw_info is not None:
            add_linearham_info(sw_info, [line])
        else:
            print '% restrict_to_iseqs(line, iseqs_to_keep, glfo, sw_info=None) needs sw_info to re-add existing \'linearham-info\' key to an annotation' % color('yellow', 'warning')

# ----------------------------------------------------------------------------------------
def print_true_events(glfo, reco_info, line, print_naive_seqs=False, full_true_partition=None, extra_str='    '):
    """ print the true events which contain the seqs in <line> """
    true_naive_seqs = []
    true_partition_of_line_uids = get_partition_from_reco_info(reco_info, ids=line['unique_ids'])  # *not* in general the same clusters as in the complete true partition, since <line['unique_ids']> may not contain all uids from all clusters from which it contains representatives
    if full_true_partition is None:
        full_true_partition = get_partition_from_reco_info(reco_info)
    for uids in true_partition_of_line_uids:  # make a multi-seq line that has all the seqs from this clonal family
        full_true_clusters = [c for c in full_true_partition if len(set(c) & set(uids_and_dups(line))) > 0]
        assert len(full_true_clusters) == 1
        missing_uids = set(full_true_clusters[0]) - set(uids_and_dups(line))
        missing_str = '' if len(missing_uids) == 0 else '   missing %d/%d sequences from actual true cluster (but includes %d duplicates not shown below)' % (len(missing_uids), len(full_true_clusters[0]), len(uids_and_dups(line)) - len(uids))

        multiline = synthesize_multi_seq_line_from_reco_info(uids, reco_info)
        if line['fv_insertion'] != '' and multiline['fv_insertion'] == '':
            extra_str = ' '*len(line['fv_insertion']) + extra_str  # aligns true + inferred vertically
        print_reco_event(multiline, extra_str=extra_str, label=color('green', 'true:') + missing_str)
        true_naive_seqs.append(multiline['naive_seq'])

    if print_naive_seqs:
        print '      naive sequences:'
        for tseq in true_naive_seqs:
            color_mutants(tseq, line['naive_seq'], print_result=True, print_hfrac=True, ref_label='true ', extra_str='          ')

# ----------------------------------------------------------------------------------------
def print_reco_event(line, one_line=False, extra_str='', label='', post_label='', queries_to_emphasize=None):
    duplicate_counts = [(u, line['unique_ids'].count(u)) for u in line['unique_ids']]
    duplicated_uids = {u : c for u, c in duplicate_counts if c > 1}
    if len(line['unique_ids']) > 1:
        label += '%s%d sequences with %.1f mean mutations (%.1f%%)' % ('' if label == '' else '    ', len(line['unique_ids']), numpy.mean(line['n_mutations']), 100*numpy.mean(line['mut_freqs']))
    for iseq in range(len(line['unique_ids'])):
        prutils.print_seq_in_reco_event(line, iseq, extra_str=extra_str, label=(label + post_label if iseq==0 else ''), one_line=(iseq>0), queries_to_emphasize=queries_to_emphasize, duplicated_uids=duplicated_uids)

#----------------------------------------------------------------------------------------
def sanitize_name(name):
    """ Replace characters in gene names that make crappy filenames. """
    saniname = name.replace('*', '_star_')
    saniname = saniname.replace('/', '_slash_')
    return saniname

#----------------------------------------------------------------------------------------
def unsanitize_name(name):
    """ Re-replace characters in gene names that make crappy filenames. """
    unsaniname = name.replace('_star_', '*')
    unsaniname = unsaniname.replace('_slash_', '/')
    return unsaniname

# ----------------------------------------------------------------------------------------
def get_locus(inputstr):
    """ return locus given gene or gl fname """
    locus = inputstr[:3].lower()  # only need the .lower() if it's a gene name
    if locus not in loci:
        raise Exception('couldn\'t get locus from input string \'%s\'' % inputstr)
    return locus

# ----------------------------------------------------------------------------------------
def get_region(inputstr, allow_constant=False):
    """ return v, d, or j of gene or gl fname """
    region = inputstr[3].lower()  # only need the .lower() if it's a gene name
    if not allow_constant:
        allowed_regions = regions
    else:
        allowed_regions = regions + constant_regions
    if region not in allowed_regions:
        raise Exception('unexpected region %s from %s (expected one of %s)' % (region, inputstr, allowed_regions))
    return region

# ----------------------------------------------------------------------------------------
def are_alleles(gene1, gene2):
    return primary_version(gene1) == primary_version(gene2) and sub_version(gene1) == sub_version(gene2)

# ----------------------------------------------------------------------------------------
def construct_valid_gene_name(gene, locus=None, region=None, default_allele_str='x', debug=False):  # kind of duplicates too much of split_gene(), but I don't want to rewrite split_gene() to be robust to all the ways a gene name can be broken
    try:  # if it's ok, don't do anything
        split_gene(gene)
        return gene
    except:
        pass

    if debug:
        initial_name = gene

    if len(gene) < 4 or gene[:3].lower() not in loci or gene[3].lower() not in regions:
        if locus is not None or region is not None:
            gene = locus.upper() + region.upper() + gene  # just tack (e.g.) 'IGHV' on the fron of whatever crap was originall there
        else:
            raise Exception('gene name %s doesn\'t have locus/region info, and it wasn\'t passed to us' % gene)

    if debug:
        middle_name = gene

    if gene.count('*') == 0:
        gene = gene + '*' + default_allele_str
    elif gene.count('*') > 1:
        gene = gene.replace('*', '.s.') + '*' + default_allele_str

    if debug:
        print '  %-25s  -->  %-25s  --> %-25s' % (initial_name, middle_name if middle_name != initial_name else '-', gene if gene != middle_name else '-')

    return gene

# ----------------------------------------------------------------------------------------
def split_gene(gene):
    """ returns (primary version, sub version, allele) """
    # make sure {IG,TR}{[HKL],[abgd]}[VDJ] is at the start, and there's a *
    if '_star_' in gene or '_slash_' in gene:
        raise Exception('gene name \'%s\' isn\'t entirely unsanitized' % gene)
    if gene[:4] != get_locus(gene).upper() + get_region(gene).upper():
        raise Exception('unexpected string in gene name %s' % gene)
    if gene.count('*') != 1:
        raise Exception('expected exactly 1 \'*\' in %s but found %d' % (gene, gene.count('*')))

    if '-' in gene and gene.find('-') < gene.find('*'):  # Js (and a few Vs) don't have sub versions
        primary_version = gene[4 : gene.find('-')]  # the bit between the IG[HKL][VDJ] and the first dash (sometimes there's a second dash as well)
        sub_version = gene[gene.find('-') + 1 : gene.find('*')]  # the bit between the first dash and the star
        allele = gene[gene.find('*') + 1 : ]  # the bit after the star
        if gene != get_locus(gene).upper() + get_region(gene).upper() + primary_version + '-' + sub_version + '*' + allele:
            raise Exception('couldn\'t build gene name %s from %s %s %s' % (gene, primary_version, sub_version, allele))
    else:
        primary_version = gene[4 : gene.find('*')]  # the bit between the IG[HKL][VDJ] and the star
        sub_version = None
        allele = gene[gene.find('*') + 1 : ]  # the bit after the star
        if gene != get_locus(gene).upper() + get_region(gene).upper() + primary_version + '*' + allele:
            raise Exception('couldn\'t build gene name %s from %s %s' % (gene, primary_version, allele))

    return primary_version, sub_version, allele

# ----------------------------------------------------------------------------------------
def shorten_gene_name(name, use_one_based_indexing=False, n_max_mutstrs=3):
    if name[:2] != 'IG':
        raise Exception('bad node name %s' % name)

    pv, sv, al = split_gene(name)
    if glutils.is_novel(name):
        _, template_name, mutstrs = glutils.split_inferred_allele_name(name)
        if use_one_based_indexing:
            mutstrs = [('%s%d%s' % (mstr[0], int(mstr[1:-1]) + 1, mstr[-1])) for mstr in mutstrs]
        if mutstrs is None:
            al = '%s (+...)' % (allele(template_name))
        elif len(mutstrs) < n_max_mutstrs:
            al = ('%s+%s' % (allele(template_name), '.'.join(mutstrs)))
        else:
            al = '%s (+%d snp%s)' % (allele(template_name), len(mutstrs), plural(len(mutstrs)))
    if sv is not None:
        return '%s-%s*%s' % (pv, sv, al)
    else:
        return '%s*%s' % (pv, al)

# ----------------------------------------------------------------------------------------
def rejoin_gene(locus, region, primary_version, sub_version, allele):
    """ reverse the action of split_gene() """
    return_str = locus.upper() + region.upper() + primary_version
    if sub_version is not None:  # e.g. J genes typically don't have sub-versions
        return_str += '-' + sub_version
    return return_str + '*' + allele

# ----------------------------------------------------------------------------------------
def primary_version(gene):
    return split_gene(gene)[0]

# ----------------------------------------------------------------------------------------
def gene_family(gene):  # same as primary_version(), except ignore stuff after the slash, e.g. 1/OR15 --> 1
    return primary_version(gene).split('/')[0].replace('D', '')

# ----------------------------------------------------------------------------------------
def sub_version(gene):
    return split_gene(gene)[1]

# ----------------------------------------------------------------------------------------
def allele(gene):
    return split_gene(gene)[2]

# ----------------------------------------------------------------------------------------
def is_constant_gene(gene):
    region = get_region(gene, allow_constant=True)
    if region not in constant_regions:
        return False
    if region != 'd':
        return True
    pv, sv, allele = split_gene(gene)
    if pv == '' and sv is None:  # constant region d is like IGHD*01
        return True
    return False

# ----------------------------------------------------------------------------------------
def are_same_primary_version(gene1, gene2):
    """
    Return true if the bit up to the dash is the same.
    """
    if get_region(gene1) != get_region(gene2):
        return False
    if primary_version(gene1) != primary_version(gene2):
        return False
    return True

# ----------------------------------------------------------------------------------------
def separate_into_allelic_groups(glfo, allele_prevalence_freqs=None, debug=False):  # prevalence freqs are just for printing
    allelic_groups = {r : {} for r in regions}
    for region in regions:
        for gene in glfo['seqs'][region]:
            primary_version, sub_version, allele = split_gene(gene)
            if primary_version not in allelic_groups[region]:
                allelic_groups[region][primary_version] = {}
            if sub_version not in allelic_groups[region][primary_version]:
                allelic_groups[region][primary_version][sub_version] = set()
            allelic_groups[region][primary_version][sub_version].add(gene)
    if debug:
        for r in regions:
            print '%s%77s' % (color('reverse_video', color('green', r)), 'percent prevalence' if allele_prevalence_freqs is not None else '')
            for p in sorted(allelic_groups[r]):
                print '    %15s' % p
                for s in sorted(allelic_groups[r][p]):
                    print '        %15s      %s' % (s, ' '.join([color_gene(g, width=14) for g in allelic_groups[r][p][s]])),
                    if len(allelic_groups[r][p][s]) < 2:  # won't work if anybody has more than two alleles
                        print '%14s' % '',
                    if allele_prevalence_freqs is not None:
                        print '  %s' % ' '.join([('%4.1f' % (100 *allele_prevalence_freqs[r][g])) for g in allelic_groups[r][p][s]]),
                    print ''
    return allelic_groups  # NOTE doesn't return the same thing as separate_into_snp_groups()

# ----------------------------------------------------------------------------------------
def separate_into_snp_groups(glfo, region, n_max_snps, genelist=None, debug=False):  # NOTE <n_max_snps> corresponds to v, whereas d and j are rescaled according to their lengths
    """ where each class contains all alleles with the same length (up to cyst if v), and within some snp threshold (n_max_v_snps for v)"""
    def getseq(gene):
        seq = glfo['seqs'][region][gene]
        if region == 'v':  # only go up through the end of the cysteine
            cpos = cdn_pos(glfo, region, gene)
            seq = seq[:cpos + 3]
        return seq
    def in_this_class(classfo, seq):
        for gfo in classfo:
            if len(gfo['seq']) != len(seq):
                continue
            hdist = hamming_distance(gfo['seq'], seq)
            if hdist < n_max_snps:  # if this gene is close to any gene in the class, add it to this class
                snp_groups[snp_groups.index(classfo)].append({'gene' : gene, 'seq' : seq, 'hdist' : hdist})
                return True
        return False  # if we fall through, nobody in this class was close to <seq>

    if genelist is None:
        genelist = glfo['seqs'][region].keys()
    snp_groups = []
    for gene in genelist:
        seq = getseq(gene)
        add_new_class = True  # to begin with, assume we'll add a new class for this gene
        for classfo in snp_groups:  # then check if, instead, this gene belongs in any of the existing classes
            if in_this_class(classfo, seq):
                add_new_class = False
                break
        if add_new_class:
            snp_groups.append([{'gene' : gene, 'seq' : seq, 'hdist' : 0}, ])

    if debug:
        print 'separated %s genes into %d groups separated by %d snps:' % (region, len(snp_groups), n_max_snps)
        glutils.print_glfo(glfo, gene_groups={region : [(str(igroup), {gfo['gene'] : gfo['seq'] for gfo in snp_groups[igroup]}) for igroup in range(len(snp_groups))]})

    return snp_groups  # NOTE this is a list of lists of dicts, whereas separate_into_allelic_groups() returns a dict of region-keyed dicts

# ----------------------------------------------------------------------------------------
def read_single_gene_count(indir, gene, expect_zero_counts=False, debug=False):
    region = get_region(gene)
    count = 0
    with open(indir + '/' + region + '_gene-probs.csv', 'r') as infile:  # NOTE this ignores correlations... which I think is actually ok, but it wouldn't hurt to think through it again at some point
        reader = csv.DictReader(infile)
        for line in reader:
            if line[region + '_gene'] == gene:
                count = int(line['count'])
                break

    if count == 0 and not expect_zero_counts:
        print '          %s %s not found in %s_gene-probs.csv, returning zero' % (color('red', 'warning'), gene, region)

    if debug:
        print '    read %d observations of %s from %s' % (count, color_gene(gene), indir)

    return count

# ----------------------------------------------------------------------------------------
def read_overall_gene_probs(indir, only_gene=None, normalize=True, expect_zero_counts=False, debug=False):
    """
    Return the observed counts/probabilities of choosing each gene version.
    If <normalize> then return probabilities
    If <only_gene> is specified, just return the prob/count for that gene  NOTE but don't forget read_single_gene_count() above ^, which I think probably does the same thing
    """
    counts, probs = {r : {} for r in regions}, {r : {} for r in regions}
    for region in regions:
        total = 0
        with open(indir + '/' + region + '_gene-probs.csv', 'r') as infile:  # NOTE this ignores correlations... which I think is actually ok, but it wouldn't hurt to think through it again at some point
            reader = csv.DictReader(infile)
            for line in reader:
                line_count = int(line['count'])
                gene = line[region + '_gene']
                total += line_count
                if gene not in counts[region]:
                    counts[region][gene] = 0
                counts[region][gene] += line_count
        if total < 1:
            raise Exception('less than one count in %s' % indir + '/' + region + '_gene-probs.csv')
        for gene in counts[region]:
            probs[region][gene] = float(counts[region][gene]) / total

    if debug:
        for region in regions:
            print '  %s' % color('green', region)
            for gene, count in sorted(counts[region].items(), key=operator.itemgetter(1), reverse=True):
                print '    %5d  %5.4f   %s' % (count, probs[region][gene], color_gene(gene, width='default'))

    if only_gene is not None and only_gene not in counts[get_region(only_gene)]:
        if not expect_zero_counts:
            print '      WARNING %s not found in overall gene probs, returning zero' % only_gene
        if normalize:
            return 0.0
        else:
            return 0

    if only_gene is None:
        if normalize:
            return probs
        else:
            return counts
    else:
        if normalize:
            return probs[get_region(only_gene)][only_gene]
        else:
            return counts[get_region(only_gene)][only_gene]

# ----------------------------------------------------------------------------------------
def get_genes_with_enough_counts(parameter_dir, min_prevalence_fractions, debug=False):
    if debug:
        print '  applying min gene prevalence fractions: %s' % '  '.join(('%s %.4f' % (r, min_prevalence_fractions[r])) for r in regions)
    gene_freqs = read_overall_gene_probs(parameter_dir, normalize=True, debug=debug)
    genes_with_enough_counts = set([g for r in regions for g, f in gene_freqs[r].items() if f > min_prevalence_fractions[r]])  # this is kind of weird because <gene_freqs> of course normalizes within each region, but then we mash all the regions together in the list, but it's all ok
    if debug:
        print '   removed genes:'
        for region in regions:
            genes_without_enough_counts = set(gene_freqs[region]) - genes_with_enough_counts
            print '      %s   %s' % (color('green', region), color_genes(sorted(genes_without_enough_counts)))
    return genes_with_enough_counts

# ----------------------------------------------------------------------------------------
def find_replacement_genes(param_dir, min_counts, gene_name=None, debug=False, all_from_region=''):  # NOTE if <gene_name> isn't in <param_dir>, it won't be among the returned genes
    if gene_name is not None:  # if you specify <gene_name> you shouldn't specify <all_from_region>
        assert all_from_region == ''
        region = get_region(gene_name)
    else:  # and vice versa
        assert all_from_region in regions
        assert min_counts == -1
        region = all_from_region
    lists = OrderedDict()  # we want to try alleles first, then primary versions, then everything and it's mother
    lists['allele'] = []  # list of genes that are alleles of <gene_name>
    lists['primary_version'] = []  # same primary version as <gene_name>
    lists['all'] = []  # give up and return everything
    with open(param_dir + '/' + region + '_gene-probs.csv', 'r') as infile:  # NOTE note this ignores correlations... which I think is actually ok, but it wouldn't hurt to think through it again at some point
        reader = csv.DictReader(infile)
        for line in reader:
            gene = line[region + '_gene']
            count = int(line['count'])
            vals = {'gene':gene, 'count':count}
            if all_from_region == '':
                if are_alleles(gene, gene_name):
                    lists['allele'].append(vals)
                if are_same_primary_version(gene, gene_name):
                    lists['primary_version'].append(vals)
            lists['all'].append(vals)

    if all_from_region != '':
        return [vals['gene'] for vals in lists['all']]
    for list_type in lists:
        total_counts = sum([vals['count'] for vals in lists[list_type]])
        if total_counts >= min_counts:
            return_list = [vals['gene'] for vals in lists[list_type]]
            if debug:
                print '      returning all %s for %s (%d gene%s, %d total counts)' % (list_type + 's', color_gene(gene_name), len(return_list), plural(len(return_list)), total_counts)
            return return_list
        else:
            if debug:
                print '      not enough counts in %s' % (list_type + 's')

    raise Exception('couldn\'t find enough counts among genes for %s in %s (found %d, needed %d -- to decrease this minimum set --min-observations-per-gene, although note that you\'re probably getting this exception because you have too few events to have very informative distributions)' % (gene_name, param_dir, total_counts, min_counts))

    # print '    \nWARNING return default gene %s \'cause I couldn\'t find anything remotely resembling %s' % (color_gene(hackey_default_gene_versions[region]), color_gene(gene_name))
    # return hackey_default_gene_versions[region]

# ----------------------------------------------------------------------------------------
def hamming_distance(seq1, seq2, extra_bases=None, return_len_excluding_ambig=False, return_mutated_positions=False, align=False, amino_acid=False):
    if extra_bases is not None:
        raise Exception('not sure what this was supposed to do (or did in the past), but it doesn\'t do anything now! (a.t.m. it seems to only be set in bin/plot-germlines.py, which I think doesn\'t do anything useful any more)')
    if align:  # way the hell slower, of course
        seq1, seq2 = align_seqs(seq1, seq2)
    if len(seq1) != len(seq2):
        raise Exception('unequal length sequences %d %d:\n  %s\n  %s' % (len(seq1), len(seq2), seq1, seq2))
    if len(seq1) == 0:
        if return_len_excluding_ambig:
            return 0, 0
        else:
            return 0

    if amino_acid:
        skip_chars = set(ambiguous_amino_acids + gap_chars)
    else:
        skip_chars = set(all_ambiguous_bases + gap_chars)

    distance, len_excluding_ambig = 0, 0
    mutated_positions = []
    for ich in range(len(seq1)):  # already made sure they're the same length
        if seq1[ich] in skip_chars or seq2[ich] in skip_chars:
            continue
        len_excluding_ambig += 1
        if seq1[ich] != seq2[ich]:
            distance += 1
            if return_mutated_positions:
                mutated_positions.append(ich)

    if return_len_excluding_ambig and return_mutated_positions:
        return distance, len_excluding_ambig, mutated_positions
    elif return_len_excluding_ambig:
        return distance, len_excluding_ambig
    elif return_mutated_positions:
        return distance, mutated_positions
    else:
        return distance

# ----------------------------------------------------------------------------------------
def hamming_fraction(seq1, seq2, extra_bases=None, also_return_distance=False, amino_acid=False):  # NOTE use hamming_distance() to get the positions (yeah, I should eventually add it here as well)
    distance, len_excluding_ambig = hamming_distance(seq1, seq2, extra_bases=extra_bases, return_len_excluding_ambig=True, amino_acid=amino_acid)

    fraction = 0.
    if len_excluding_ambig > 0:
        fraction = distance / float(len_excluding_ambig)

    if also_return_distance:
        return fraction, distance
    else:
        return fraction

# ----------------------------------------------------------------------------------------
def mean_pairwise_hfrac(seqlist):
    if len(seqlist) < 2:
        return 0.
    return numpy.mean([hamming_fraction(s1, s2) for s1, s2 in itertools.combinations(seqlist, 2)])

# ----------------------------------------------------------------------------------------
def subset_sequences(line, restrict_to_region=None, exclusion_3p=None, iseq=None):
    # NOTE don't call with <iseq> directly, instead use subset_iseq() below

    naive_seq = line['naive_seq']  # NOTE this includes the fv and jf insertions
    if iseq is None:
        muted_seqs = copy.deepcopy(line['seqs'])
    else:
        muted_seqs = [line['seqs'][iseq]]

    if restrict_to_region != '':  # NOTE this is very similar to code in performanceplotter. I should eventually cut it out of there and combine them, but I'm nervous a.t.m. because of all the complications there of having the true *and* inferred sequences so I'm punting
        if restrict_to_region in regions:
            bounds = line['regional_bounds'][restrict_to_region]
        elif restrict_to_region == 'cdr3':
            bounds = (line['codon_positions']['v'], line['codon_positions']['j'] + 3)
        else:
            assert False
        if exclusion_3p is not None:  # see NOTE in performanceplotter.hamming_to_true_naive()
            bounds = (bounds[0], max(bounds[0], bounds[1] - exclusion_3p))
        naive_seq = naive_seq[bounds[0] : bounds[1]]
        muted_seqs = [mseq[bounds[0] : bounds[1]] for mseq in muted_seqs]

    return naive_seq, muted_seqs

# ----------------------------------------------------------------------------------------
def subset_iseq(line, iseq, restrict_to_region=None, exclusion_3p=None):
    naive_seq, muted_seqs = subset_sequences(line, iseq=iseq, restrict_to_region=restrict_to_region, exclusion_3p=exclusion_3p)
    return naive_seq, muted_seqs[0]  # if <iseq> is specified, it's the only one in the list (this is kind of confusing, but it's less wasteful)

# ----------------------------------------------------------------------------------------
def get_n_muted(line, iseq, restrict_to_region='', return_mutated_positions=False):
    naive_seq, muted_seq = subset_iseq(line, iseq, restrict_to_region=restrict_to_region)
    return hamming_distance(naive_seq, muted_seq, return_mutated_positions=return_mutated_positions)

# ----------------------------------------------------------------------------------------
def get_mutation_rate(line, iseq, restrict_to_region=''):
    naive_seq, muted_seq = subset_iseq(line, iseq, restrict_to_region=restrict_to_region)
    return hamming_fraction(naive_seq, muted_seq)

# ----------------------------------------------------------------------------------------
def get_mutation_rate_and_n_muted(line, iseq, restrict_to_region='', exclusion_3p=None):
    naive_seq, muted_seq = subset_iseq(line, iseq, restrict_to_region=restrict_to_region, exclusion_3p=exclusion_3p)
    fraction, distance = hamming_fraction(naive_seq, muted_seq, also_return_distance=True)
    return fraction, distance

# ----------------------------------------------------------------------------------------
def get_sfs_occurence_info(line, restrict_to_region=None, debug=False):
    if restrict_to_region is None:
        naive_seq, muted_seqs = line['naive_seq'], line['seqs']  # I could just call subset_sequences() to get this, but this is a little faster since we know we don't need the copy.deepcopy()
    else:
        naive_seq, muted_seqs = subset_sequences(line, restrict_to_region=restrict_to_region)
    if debug:
        print '  %d %ssequences' % (len(muted_seqs), '%s region ' % restrict_to_region if restrict_to_region is not None else '')
    mutated_positions = [hamming_distance(naive_seq, mseq, return_mutated_positions=True)[1] for mseq in muted_seqs]
    all_positions = sorted(set([p for mp in mutated_positions for p in mp]))
    if debug:
        print '    %.2f mean mutations  %s' % (numpy.mean([len(mpositions) for mpositions in mutated_positions]), ' '.join([str(len(mpositions)) for mpositions in mutated_positions]))
        print '    %d positions are mutated in at least one sequence' % len(all_positions)
    occurence_indices = [[i for i in range(len(line['unique_ids'])) if p in mutated_positions[i]] for p in all_positions]  # for each position in <all_positions>, a list of the sequence indices that have a mutation at that position
    occurence_fractions = [len(iocc) / float(len(line['unique_ids'])) for iocc in occurence_indices]  # fraction of all sequences that have a mutation at each position in <all_positions>
    return occurence_indices, occurence_fractions

# ----------------------------------------------------------------------------------------
def fay_wu_h(line, restrict_to_region=None, occurence_indices=None, n_seqs=None, debug=False):  # from: https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1461156/pdf/10880498.pdf and https://www.biorxiv.org/content/biorxiv/early/2017/10/19/145052.full.pdf
    if occurence_indices is None:
        occurence_indices, _ = get_sfs_occurence_info(line, restrict_to_region=restrict_to_region, debug=debug)
        n_seqs = len(line['unique_ids'])
    else:
        assert line is None  # don't pass both of 'em
    if n_seqs == 1:
        return 0.
    mutation_multiplicities = [len(oindices) for oindices in occurence_indices]  # <oindices> is a list of the indices of sequences that had this mutation, so this gives the number of sequences that had a mutation at this position
    theta_h = 0.
    for inm in range(1, n_seqs):
        theta_h += mutation_multiplicities.count(inm) * inm * inm
    theta_h *= 2. / (n_seqs * (n_seqs - 1))

    theta_pi = 0.
    for inm in range(1, n_seqs):
        theta_pi += mutation_multiplicities.count(inm) * inm * (n_seqs - inm)
    theta_pi *= 2. / (n_seqs * (n_seqs - 1))

    if debug:
        print '   h for %d seqs:  %6.2f - %6.2f = %6.2f' % (n_seqs, theta_pi, theta_h, theta_pi - theta_h)

    return theta_pi - theta_h

# ----------------------------------------------------------------------------------------
def dot_product(naive_seq, seq1, seq2):
    _, imutes1 = hamming_distance(naive_seq, seq1, return_mutated_positions=True)
    _, imutes2 = hamming_distance(naive_seq, seq2, return_mutated_positions=True)
    both_muted = set(imutes1) & set(imutes2)
    both_muted_to_same_thing = [imut for imut in both_muted if seq1[imut] == seq2[imut]]
    dot_product = len(both_muted_to_same_thing)
    # print '    naive  %s' % naive_seq
    # print '           %s' % utils.color_mutants(naive_seq, seq1)
    # print '           %s' % utils.color_mutants(naive_seq, seq2)
    # print '    dot %d' % dot_product
    return dot_product

# ----------------------------------------------------------------------------------------
def round_to_n_digits(val, n_digits):  # round <val> to <n_digits> significant figures
    if val == 0:
        return val
    return round(val, n_digits - int(math.floor(math.log10(abs(val)))) - 1)

# ----------------------------------------------------------------------------------------
def get_key(names):
    """
    Return a hashable combination of the two query names that's the same if we reverse their order.
    """
    return '.'.join(sorted([str(name) for name in names]))

# ----------------------------------------------------------------------------------------
def split_key(key):
    """
    Reverse the action of get_key().
    NOTE does not necessarily give a_ and b_ in the same order, though
    NOTE also that b_name may not be the same (if 0), and this just returns strings, even if original names were ints
    """
    # assert len(re.findall('.', key)) == 1  # make sure none of the keys had a dot in it
    return key.split('.')

# ----------------------------------------------------------------------------------------
def prep_dir(dirname, wildlings=None, subdirs=None, rm_subdirs=False, fname=None, allow_other_files=False):
    """
    Make <dirname> if it d.n.e.
    Also, if shell glob <wildling> is specified, remove existing files which are thereby matched.
    """
    if fname is not None:  # passed in a file name, and we want to prep the file's dir
        assert dirname is None
        dirname = os.path.dirname(fname)
        if dirname == '' or dirname[0] != '/':
            dirname = '/'.join([pn for pn in [os.getcwd(), dirname] if pn != ''])

    if wildlings is None:
        wildlings = []
    elif isinstance(wildlings, basestring):  # allow to pass in just a string, instead of a list of strings
        wildlings = [wildlings, ]

    if subdirs is not None:  # clean out the subdirs first
        for subdir in subdirs:
            prep_dir(dirname + '/' + subdir, wildlings=wildlings, allow_other_files=allow_other_files)
            if rm_subdirs:
                os.rmdir(dirname + '/' + subdir)

    if os.path.exists(dirname):
        for wild in wildlings:
            for ftmp in glob.glob(dirname + '/' + wild):
                if os.path.exists(ftmp):
                    os.remove(ftmp)
                else:
                    print '%s file %s exists but then it doesn\'t' % (color('red', 'wtf'), ftmp)
        remaining_files = [fn for fn in os.listdir(dirname) if subdirs is None or fn not in subdirs]  # allow subdirs to still be present
        if len(remaining_files) > 0 and not allow_other_files:  # make sure there's no other files in the dir
            raise Exception('files (%s) remain in %s despite wildlings %s' % (' '.join(['\'' + fn + '\'' for fn in remaining_files]), dirname, wildlings))
    else:
        os.makedirs(dirname)

# ----------------------------------------------------------------------------------------
def rmdir(dname, fnames=None):
    if fnames is not None:
        for fn in fnames:
            if os.path.exists(fn):
                os.remove(fn)
            else:
                print '  %s expected to clean up file, but it\'s missing: %s' % (color('yellow', 'warning'), fn)
    remaining_files = os.listdir(dname)
    if len(remaining_files) > 0:
        raise Exception('files remain in %s, so can\'t rm dir: %s' % (dname, ' '.join(remaining_files)))
    os.rmdir(dname)

# ----------------------------------------------------------------------------------------
def process_input_line(info, skip_literal_eval=False):
    """
    Attempt to convert all the keys and values in <info> according to the specifications in <io_column_configs> (e.g. splitting lists, casting to int/float, etc).
    """

    if 'v_gene' in info and info['v_gene'] == '':
        return

    if 'seq' in info:  # old simulation files
        for key in ['unique_id', 'seq', 'indelfo']:
            if key not in info:
                continue
            info[key + 's'] = info[key]
            del info[key]
        if 'indelfos' not in info:  # hm, at least some old sim files don't have 'indelfo'
            info['indelfos'] = str(indelutils.get_empty_indel())
        info['indelfos'] = '[' + info['indelfos'] + ']'
        info['input_seqs'] = info['seqs']

    for key in info:
        if info[key] == '':  # handle these below, once we know how many seqs in the line
            continue
        convert_fcn = conversion_fcns.get(key, pass_fcn)
        if skip_literal_eval and convert_fcn is ast.literal_eval:  # it's really slow (compared to the other conversions at least), and it's only for keys that we hardly ever use
            continue
        if key in io_column_configs['lists-of-lists']:
            info[key] = convert_fcn(info[key].split(';'))
        elif key in io_column_configs['lists']:
            info[key] = [convert_fcn(val) for val in info[key].split(':')]
        else:
            info[key] = convert_fcn(info[key])

    # this column is called 'seqs' internally (for conciseness and to avoid rewriting a ton of stuff) but is called 'indel_reversed_seqs' in the output file to avoid user confusion
    if 'indel_reversed_seqs' in info and 'input_seqs' in info:  # new-style csv output and simulation files, i.e. it stores 'indel_reversed_seqs' instead of 'seqs'
        if info['indel_reversed_seqs'] == '':
            info['indel_reversed_seqs'] = ['' for _ in range(len(info['unique_ids']))]
        transfer_indel_reversed_seqs(info)
    elif 'seqs' in info:  # old-style csv output file: just copy 'em into the explicit name
        info['indel_reversed_seqs'] = info['seqs']

    # process things for which we first want to know the number of seqs in the line
    for key in [k for k in info if info[k] == '']:
        if key in io_column_configs['lists']:
            info[key] = ['' for _ in range(len(info['unique_ids']))]
        elif key in io_column_configs['lists-of-lists']:
            info[key] = [[] for _ in range(len(info['unique_ids']))]

    # NOTE indels get fixed up (espeicially/only for old-style files) in add_implicit_info(), since we want to use the implicit info to do it

    if 'all_matches' in info and isinstance(info['all_matches'], dict):  # it used to be per-family, but then I realized it should be per-sequence, so any old cache files lying around have it as per-family
        info['all_matches'] = [info['all_matches']]
    # make sure everybody's the same lengths
    for key in [k for k in info if k in io_column_configs['lists']]:
        if key == 'duplicates' and len(info[key]) != len(info['unique_ids']) and len(info[key]) == 1:  # fix problem caused by 'duplicates' being in both 'lists' and 'lists-of-lists', combined with get_line_for_output() and this fcn having the if/else blocks in opposite order (fixed now, but some files are probably lying around with the whacked out formatting)
            info[key] = info[key][0]
            info[key] = [ast.literal_eval(v) for v in info[key]]  # specifically, in get_line_for_output() 'lists' was first in the if/else block, so the list of duplicates for each sequence was str() converted rather than being converted to colon/semicolon separated string
        if len(info[key]) != len(info['unique_ids']):
            raise Exception('list length %d for %s not the same as for unique_ids %d\n  contents: %s' % (len(info[key]), key, len(info['unique_ids']), info[key]))

# ----------------------------------------------------------------------------------------
def revcomp(nuc_seq):
    if 'Bio.Seq' not in sys.modules:  # import is frequently slow af
        from Bio.Seq import Seq
    bseq = sys.modules['Bio.Seq']
    return str(bseq.Seq(nuc_seq).reverse_complement())

# ----------------------------------------------------------------------------------------
def ltranslate(nuc_seq, trim=False):  # local file translation function
    if 'Bio.Seq' not in sys.modules:  # import is frequently slow af
        from Bio.Seq import Seq
    bseq = sys.modules['Bio.Seq']
    if trim:  # this should probably be the default, but i don't want to change anything that's using the padding (even though it probably wouldn't matter)
        nuc_seq = trim_nuc_seq(nuc_seq.strip(ambig_base))
    return str(bseq.Seq(pad_nuc_seq(nuc_seq)).translate())  # the padding is annoying, but it's extremely common for bcr sequences to have lengths not a multiple of three (e.g. because out out of frame rearrangements), so easier to just always check for it

# ----------------------------------------------------------------------------------------
def get_cdr3_seq(info, iseq):  # NOTE includeds both codons, i.e. not the same as imgt definition
    return info['seqs'][iseq][info['codon_positions']['v'] : info['codon_positions']['j'] + 3]

# ----------------------------------------------------------------------------------------
def add_naive_seq_aa(line):  # NOTE similarity to block in add_extra_column()
    if 'naive_seq_aa' in line:
        return
    line['naive_seq_aa'] = ltranslate(line['naive_seq'])

# ----------------------------------------------------------------------------------------
def add_seqs_aa(line, debug=False):  # NOTE similarity to block in add_extra_column()
    if 'seqs_aa' in line:
        return
    def tmpseq(tseq):  # this duplicates the arithmetic in waterer that pads things to the same length, but we do that after a bunch of places where we might call this fcn, so we need to check for it here as well
        fv_xtra, v_5p_xtra = 0, 0
        if len(line['fv_insertion']) % 3 != 0:
            fv_xtra = 3 - len(line['fv_insertion']) % 3
            tseq = fv_xtra * ambig_base + tseq
        if line['v_5p_del'] % 3 != 0:
            v_5p_xtra = line['v_5p_del'] % 3
            tseq = v_5p_xtra * ambig_base + tseq
        if debug:
            print '  fv: 3 - %d%%3: %d  v_5p: %d%%3: %d' % (len(line['fv_insertion']), fv_xtra, line['v_5p_del'], v_5p_xtra)  # NOTE the first one is kind of wrong, since it's 0 if the %3 is 0
        return tseq
    line['seqs_aa'] = [ltranslate(tmpseq(s)) for s in line['seqs']]
    if debug:
        print pad_lines('\n'.join(line['seqs_aa']))

# ----------------------------------------------------------------------------------------
def pad_nuc_seq(nseq):  # if length not multiple of three, pad on right with Ns
    if len(nseq) % 3 != 0:
        nseq += 'N' * (3 - (len(nseq) % 3))
    return nseq

# ----------------------------------------------------------------------------------------
def trim_nuc_seq(nseq):  # if length not multiple of three, trim extras from the right side
    if len(nseq) % 3 != 0:
        nseq = nseq[ : len(nseq) - (len(nseq) % 3)]
    return nseq

# ----------------------------------------------------------------------------------------
def add_extra_column(key, info, outfo, glfo=None, definitely_add_all_columns_for_csv=False):
    # NOTE use <info> to calculate all quantities, *then* put them in <outfo>: <outfo> only has the stuff that'll get written to the file, so can be missing things that are needed for calculations
    if key == 'cdr3_seqs':
        outfo[key] = [get_cdr3_seq(info, iseq) for iseq in range(len(info['unique_ids']))]
    elif key == 'full_coding_naive_seq':
        assert glfo is not None
        delstr_5p = glfo['seqs']['v'][info['v_gene']][ : info['v_5p_del']]  # bit missing from the input sequence
        outfo[key] = delstr_5p + info['naive_seq']
        if info['j_3p_del'] > 0:
            delstr_3p = glfo['seqs']['j'][info['j_gene']][-info['j_3p_del'] : ]
            outfo[key] += delstr_3p
        # print outfo['unique_ids']
        # color_mutants(info['naive_seq'], outfo[key], print_result=True, align=True, extra_str='  ')
    elif key == 'full_coding_input_seqs':
        full_coding_input_seqs = [info['v_5p_del'] * ambig_base + info['input_seqs'][iseq] + info['j_3p_del'] * ambig_base for iseq in range(len(info['unique_ids']))]
        outfo[key] = full_coding_input_seqs
        # for iseq in range(len(info['unique_ids'])):
        #     print info['unique_ids'][iseq]
        #     color_mutants(info['input_seqs'][iseq], full_coding_input_seqs[iseq], print_result=True, align=True, extra_str='  ')
    elif key == 'consensus_seq':
        outfo[key] = cons_seq_of_line(info)
    elif key == 'consensus_seq_aa':
        outfo[key] = cons_seq_of_line(info, aa=True)
    elif key == 'naive_seq_aa':  # NOTE similarity to add_naive_seq_aa()
        outfo[key] = ltranslate(info['naive_seq'])
    elif key == 'seqs_aa':  # NOTE similarity to add_seqs_aa()
        outfo[key] = [ltranslate(s) for s in info['seqs']]
    elif key in ['cons_dists_nuc', 'cons_dists_aa']:
        treeutils.add_cons_dists(info, aa='_aa' in key)
        outfo[key] = info[key]  # has to be done in two steps (see note at top of fcn)
    elif key in linekeys['hmm'] + linekeys['sw'] + linekeys['simu']:  # these are added elsewhere
        if definitely_add_all_columns_for_csv:
            if key in io_column_configs['lists']:
                outfo[key] = [None for _ in info['unique_ids']]
            elif key in io_column_configs['lists-of-lists']:
                outfo[key] = [[] for _ in info['unique_ids']]
            else:
                outfo[key] = None
        else:
            return  # only here to remind you that nothing happens
    elif key in input_metafile_keys.values():  # uh, not really sure what's the best thing to do, but this only gets called on deprecated csv files, so oh well
        outfo[key] = [None for _ in info['unique_ids']]
    else:  # shouldn't actually get to here, since we already enforce utils.extra_annotation_headers as the choices for args.extra_annotation_columns
        raise Exception('column \'%s\' missing from annotation' % key)

# ----------------------------------------------------------------------------------------
def transfer_indel_reversed_seqs(line):
    # if there's no indels, we will have just written 'input_seqs' to the file, and left 'indel_reversed_seqs' empty
    line['seqs'] = [line['indel_reversed_seqs'][iseq] if line['indel_reversed_seqs'][iseq] != '' else line['input_seqs'][iseq] for iseq in range(len(line['unique_ids']))]

# ----------------------------------------------------------------------------------------
def transfer_indel_info(info, outfo):  # NOTE reverse of this happens in indelutils.deal_with_indel_stuff()
    """
    for keys in special_indel_columns_for_output: in memory, I need the indel info under the 'indelfos' key (for historical reasons that I don't want to change a.t.m.), but I want to mask that complexity for output
    """
    if special_indel_columns_for_output[0] in info:  # they're only already transferred if we're reading simulation files for merging
        for sicfo in special_indel_columns_for_output:
            outfo[sicfo] = info[sicfo]
    else:
        if info['invalid']:
            return
        outfo['has_shm_indels'] = [indelutils.has_indels(ifo) for ifo in info['indelfos']]
        outfo['qr_gap_seqs'] = [ifo['qr_gap_seq'] for ifo in info['indelfos']]
        outfo['gl_gap_seqs'] = [ifo['gl_gap_seq'] for ifo in info['indelfos']]
        outfo['indel_reversed_seqs'] = ['' if not indelutils.has_indels(info['indelfos'][iseq]) else info['indel_reversed_seqs'][iseq] for iseq in range(len(info['unique_ids']))]  # if no indels, it's the same as 'input_seqs', so set indel_reversed_seqs to empty strings

# ----------------------------------------------------------------------------------------
def get_line_for_output(headers, info, glfo=None):
    """ Reverse the action of process_input_line() """
    # NOTE only used by (deprecated) csv writer now
    outfo = {}
    transfer_indel_info(info, outfo)
    for key in headers:
        if key in ['seqs', 'indelfo', 'indelfos']:
            continue

        if key not in special_indel_columns_for_output:  # these four were already added to <outfo> (and are not in <info>), but everyone else needs to be transferred from <info> to <outfo>
            if key in info:
                if key in io_column_configs['lists-of-lists']:
                    outfo[key] = copy.deepcopy(info[key])
                else:
                    outfo[key] = info[key]
            else:
                add_extra_column(key, info, outfo, glfo=glfo, definitely_add_all_columns_for_csv=True)

        str_fcn = str
        if key in io_column_configs['floats']:
            str_fcn = repr  # keeps it from losing precision (we only care because we want it to match expectation if we read it back in)

        if key in io_column_configs['lists-of-lists']:
            if '_per_gene_support' in key:
                outfo[key] = outfo[key].items()
            for isl in range(len(outfo[key])):
                outfo[key][isl] = ':'.join([str_fcn(s) for s in outfo[key][isl]])
            outfo[key] = ';'.join(outfo[key])
        elif key in io_column_configs['lists']:
            outfo[key] = ':'.join([str_fcn(v) for v in outfo[key]])
        else:
            outfo[key] = str_fcn(outfo[key])

        # if key == 'tree':  # if this is commented, the newick tree strings get written with trailing newline, which looks weird when you look at the .csv by hand, but otherwise works just fine
        #     outfo[key] = outfo[key].strip()

    return outfo

# ----------------------------------------------------------------------------------------
def merge_simulation_files(outfname, file_list, headers, cleanup=True, n_total_expected=None, n_per_proc_expected=None, use_pyyaml=False, dont_write_git_info=False):
    if getsuffix(outfname) == '.csv':  # old way
        n_event_list, n_seq_list = merge_csvs(outfname, file_list)
    elif getsuffix(outfname) == '.yaml':  # new way
        n_event_list, n_seq_list = merge_yamls(outfname, file_list, headers, use_pyyaml=use_pyyaml, dont_write_git_info=dont_write_git_info)
    else:
        raise Exception('unhandled annotation file suffix %s' % args.outfname)

    print '   read %d event%s with %d seqs from %d %s files' % (sum(n_event_list), plural(len(n_event_list)), sum(n_seq_list), len(file_list), getsuffix(outfname))
    if n_total_expected is not None:
        if isinstance(n_per_proc_expected, list):  # different number for each proc
            if n_event_list != n_per_proc_expected:
                raise Exception('expected events per proc (%s), different from those read from the files (%s)' % (' '.join(str(n) for n in n_per_proc_expected), ' '.join([str(n) for n in n_event_list])))
        else:  # all procs the same number
            if n_event_list.count(n_per_proc_expected) != len(n_event_list):
                raise Exception('expected %d events per proc, but read: %s' % (n_per_proc_expected, ' '.join([str(n) for n in n_event_list])))
        if n_total_expected != sum(n_event_list):
            print '  %s expected %d total events but read %d (per-file couts: %s)' % (color('yellow', 'warning'), n_total_expected, sum(n_event_list), ' '.join([str(n) for n in n_event_list]))

# ----------------------------------------------------------------------------------------
def merge_csvs(outfname, csv_list, cleanup=True):
    """ NOTE copy of merge_hmm_outputs in partitiondriver, I should really combine the two functions """
    header = None
    outfo = []
    n_event_list, n_seq_list = [], []
    for infname in csv_list:
        if getsuffix(infname) != '.csv':
            raise Exception('unhandled suffix, expected .csv: %s' % infname)
        with open(infname, 'r') as sub_outfile:
            reader = csv.DictReader(sub_outfile)
            header = reader.fieldnames
            n_event_list.append(0)
            n_seq_list.append(0)
            last_reco_id = None
            for line in reader:
                outfo.append(line)
                n_seq_list[-1] += 1
                if last_reco_id is None or line['reco_id'] != last_reco_id:
                    last_reco_id = line['reco_id']
                    n_event_list[-1] += 1
        if cleanup:
            os.remove(infname)
            os.rmdir(os.path.dirname(infname))

    outdir = '.' if os.path.dirname(outfname) == '' else os.path.dirname(outfname)
    if not os.path.exists(outdir):
        os.makedirs(outdir)
    with open(outfname, 'w') as outfile:
        writer = csv.DictWriter(outfile, header)
        writer.writeheader()
        for line in outfo:
            writer.writerow(line)

    return n_event_list, n_seq_list

# ----------------------------------------------------------------------------------------
def merge_yamls(outfname, yaml_list, headers, cleanup=True, use_pyyaml=False, dont_write_git_info=False):
    """ NOTE copy of merge_csvs(), which is (apparently) a copy of merge_hmm_outputs in partitiondriver, I should really combine the two functions """
    merged_annotation_list = []
    merged_cpath = None
    ref_glfo = None
    n_event_list, n_seq_list = [], []
    for infname in yaml_list:
        glfo, annotation_list, cpath = read_yaml_output(infname, dont_add_implicit_info=True)
        n_event_list.append(len(annotation_list))
        n_seq_list.append(sum(len(l['unique_ids']) for l in annotation_list))
        if merged_cpath is None:
            merged_cpath = cpath
        else:
            assert len(cpath.partitions) == len(merged_cpath.partitions)
            assert cpath.i_best == merged_cpath.i_best  # not sure what to do otherwise (and a.t.m. i'm only using this  to merge simulation files, which only ever have one partition)
            for ip in range(len(cpath.partitions)):
                merged_cpath.partitions[ip] += cpath.partitions[ip]  # NOTE this assumes there's no overlap between files, e.g. if it's simulation and the files are totally separate
                merged_cpath.logprobs[ip] += cpath.logprobs[ip]  # they'll be 0 for simulation, but may as well handle it
                # NOTE i think i don't need to mess with these, but not totally sure: self.n_procs, self.ccfs, self.we_have_a_ccf
        if ref_glfo is None:
            ref_glfo = glfo
        if glfo != ref_glfo:
            raise Exception('can only merge files with identical germline info')
        merged_annotation_list += annotation_list
        if cleanup:
            os.remove(infname)
            os.rmdir(os.path.dirname(infname))

    if getsuffix(outfname) != '.yaml':
        raise Exception('wrong function for %s' % outfname)
    outdir = '.' if os.path.dirname(outfname) == '' else os.path.dirname(outfname)
    if not os.path.exists(outdir):
        os.makedirs(outdir)

    write_annotations(outfname, ref_glfo, merged_annotation_list, headers, use_pyyaml=use_pyyaml, dont_write_git_info=dont_write_git_info, partition_lines=merged_cpath.get_partition_lines(True))  # set is_data to True since we can't pass in reco_info and whatnot anyway

    return n_event_list, n_seq_list

# ----------------------------------------------------------------------------------------
def get_nodelist_from_slurm_shorthand(nodestr, known_nodes, debug=False):
    if debug:
        print '    getting nodelist from \'%s\'' % nodestr

    if '[' not in nodestr and ']' not in nodestr:  # single node (don't really need this, but maybe it's a little faster)
        return [nodestr]

    # first find the indices at which there're square braces
    nodes = []
    bracketfo = []
    ilastcomma = -1  # if the first one has brackets, the "effective" comma is at -1
    thisnodestr = ''
    for ich in range(len(nodestr)):
        ch = nodestr[ich]
        if ch == ',':
            ilastcomma = ich
        if ch == '[':
            bracketfo.append({'comma' : ilastcomma, 'ibrackets' : [ich, None]})
            thisnodestr = ''
            if debug:
                print '      start bracket    %s' % nodestr[ilastcomma + 1 : ich + 1]
        elif ch == ']':
            assert bracketfo[-1]['ibrackets'][1] is None
            bracketfo[-1]['ibrackets'][1] = ich
            thisnodestr = ''
            if debug:
                print '      end bracket      %s' % nodestr[bracketfo[-1]['ibrackets'][0] : bracketfo[-1]['ibrackets'][1] + 1]

        # if we're not within a bracket info
        if len(bracketfo) == 0 or bracketfo[-1]['ibrackets'][1] is not None:
            thisnodestr += ch
            thisnodestr = thisnodestr.strip(',[]')
            if len(thisnodestr) > 1 and ch == ',':  # if we just got to a comma, and there's something worth looking at in <thisnodestr>
                nodes.append(thisnodestr)
                thisnodestr = ''
                if debug:
                    print '      add no-bracket   %s' % nodes[-1]

    if debug:
        if len(nodes) > 0:
            print '    %d bracketless nodes: %s' % (len(nodes), ' '.join(nodes))
        if len(bracketfo) > 0:
            print '      brackets:'

    # the expand the ranges in the brackets
    for bfo in bracketfo:
        ibp = bfo['ibrackets']
        original_str = nodestr[ibp[0] + 1 : ibp[1]]  # NOTE excludes the actual bracket characters
        bracketnodes = []
        for subnodestr in original_str.split(','):
            if '-' in subnodestr:  # range of node numbers
                startstoplist = [int(i) for i in subnodestr.split('-')]
                if len(startstoplist) != 2:
                    raise Exception('wtf %s' % subnodestr)
                istart, istop = startstoplist
                bracketnodes += range(istart, istop + 1)
            else: # single node
                bracketnodes.append(int(subnodestr))
        namestr = nodestr[bfo['comma'] + 1 : ibp[0]]  # the texty bit of the name (i.e. without the numbers)
        if debug:
            print '        %s: \'%s\' --> %s' % (namestr, original_str, ' '.join([str(n) for n in bracketnodes]))
        bracketnodes = [namestr + str(i) for i in bracketnodes]
        nodes += bracketnodes

    unknown_nodes = set(nodes) - set(known_nodes)
    if len(unknown_nodes) > 0:
        print '    %s unknown nodes parsed from \'%s\': %s' % (color('yellow', 'warning'), nodestr, ' '.join(unknown_nodes))

    if debug:
        print '    %d final nodes: %s' % (len(nodes), ' '.join(nodes))

    return nodes

# ----------------------------------------------------------------------------------------
def get_available_node_core_list(batch_config_fname, debug=False):  # for when you're running the whole thing within one slurm allocation, i.e. with  % salloc --nodes N ./bin/partis [...]
    if debug:
        print ''
        print '  figuring out slurm config'

    our_nodes = []

    if os.getenv('SLURM_NODELIST') is None:  # not within a slurm allocation
        if debug:
            print '  not inside a slurm allocation'
        return None

    # first get info on all nodes from config file
    nodefo = {}  # node : (that node's specifications in config file)
    with open(batch_config_fname) as bfile:
        for line in bfile:
            linefo = line.strip().split()
            node = None
            if len(linefo) > 0 and linefo[0].find('NodeName=') == 0:  # node config line
                for strfo in linefo:
                    tokenval = strfo.split('=')
                    if len(tokenval) != 2:
                        raise Exception('couldn\'t parse %s into \'=\'-separated key-val pairs' % strfo)
                    key, val = tokenval
                    if ',' in val:
                        val = val.split(',')
                    if key == 'NodeName':
                        node = val
                        # if node not in our_nodes:  # damn, doesn't work
                        #     continue
                        nodefo[node] = {}
                    if node is None or node not in nodefo:
                        raise Exception('first key wasn\'t NodeName')
                    nodefo[node][key] = val
    # multiply sockets times cores/socket
    for node, info in nodefo.items():
        if 'Sockets' not in info or 'CoresPerSocket' not in info:
            raise Exception('missing keys in: %s' % ' '.join(info.keys()))
        info['nproc'] = int(info['Sockets']) * int(info['CoresPerSocket'])
    if debug:
        print '    info for %d nodes in %s' % (len(nodefo), batch_config_fname)

    our_nodes = get_nodelist_from_slurm_shorthand(os.getenv('SLURM_NODELIST'), known_nodes=nodefo.keys())
    if len(our_nodes) == 0:
        return []

    if debug:
        print '    current allocation includes %d nodes' % len(our_nodes)

    # then info on all current allocations
    quefo = {}  # node : (number of tasks allocated to that node, including ours)
    squeue_str = subprocess.check_output(['squeue', '--format', '%.18i %.2t %.6D %R'])
    headers = ['JOBID', 'ST',  'NODES', 'NODELIST(REASON)']
    for line in squeue_str.split('\n'):
        linefo = line.strip().split()
        if len(linefo) == 0:
            continue
        if linefo[0] == 'JOBID':
            assert linefo == headers
        if linefo[headers.index('ST')] != 'R':  # skip jobs that aren't running
            continue
        nodes = get_nodelist_from_slurm_shorthand(linefo[headers.index('NODELIST(REASON)')], known_nodes=nodefo.keys())
        for node in nodes:
            if node not in our_nodes:
                continue
            if node not in nodefo:
                print '  %s node %s in squeue output but not in config file %s' % (color('yellow', 'warning'), node, batch_config_fname)
                continue
            if node not in quefo:
                quefo[node] = 0
            quefo[node] += 1  # NOTE ideally this would be the number of cores slurm gave this task, rather than 1, but I can't figure out how to that info (and the docs make it sound like it might not be possible to)

    if debug:
        print '    %d "total tasks" allocated among nodes in our current allocation' % sum(quefo.values())

    # and finally, decide how many procs we can send to each node
    corelist = []
    for node in our_nodes:
        if node not in nodefo:
            raise Exception('node %s in our allocation not in config file %s' % (node, batch_config_fname))
        if node not in quefo:
            raise Exception('node %s in our allocation not in squeue output' % node)
        n_cores_we_can_use = nodefo[node]['nproc'] - quefo[node] + 1  # add one to account for the fact that quefo[node] includes our allocation
        if n_cores_we_can_use == 0:
            print '  %s huh, n_cores_we_can_use is zero' % color('yellow', 'warning')
            n_cores_we_can_use = 1
        elif n_cores_we_can_use < 0:
            print '  %s more tasks allocated to %s than available cores: %d - %d = %d (setting n_cores_we_can_use to 1 because, uh, not sure what else to do)' % (color('yellow', 'warning'), node, nodefo[node]['nproc'], quefo[node], nodefo[node]['nproc'] - quefo[node])
            n_cores_we_can_use = 1
        corelist += [node for _ in range(n_cores_we_can_use)]

    corelist = sorted(corelist)  # easier to read if it's alphabetical

    if debug:
        print '    %d available cores:' % len(corelist)
        for node in set(corelist):
            print '        %d  %s' % (corelist.count(node), node)

    if len(corelist) == 0:
        return None

    return corelist

# ----------------------------------------------------------------------------------------
def set_slurm_nodelist(cmdfos, batch_config_fname=None, debug=False):
    # get info about any existing slurm allocation
    corelist = None
    n_procs = len(cmdfos)
    if not os.path.exists(batch_config_fname):
        print '  %s specified --batch-config-fname %s doesn\'t exist' % (color('yellow', 'warning'), batch_config_fname)
    else:
        corelist = get_available_node_core_list(batch_config_fname)  # list of nodes within our current allocation (empty if there isn't one), with each node present once for each core that we've been allocated on that node
        if corelist is not None and len(corelist) < n_procs:
            if 1.5 * len(corelist) < n_procs:
                print '  %s many fewer cores %d than processes %d' % (color('yellow', 'warning'), len(corelist), n_procs)
                print '      corelist: %s' % ' '.join(corelist)
            while len(corelist) < n_procs:
                corelist += sorted(set(corelist))  # add each node once each time through

    if corelist is None:
        return

    if debug:
        print '    %d final cores for %d procs' % (len(corelist), n_procs)
        print '        iproc     node'
        for iproc in range(n_procs):
            print '          %-3d    %s' % (iproc, corelist[iproc])
    assert len(corelist) >= n_procs
    for iproc in range(n_procs):  # it's kind of weird to keep batch_system and batch_options as keyword args while putting nodelist into the cmdfos, but they're just different enough that it makes sense (we're only using nodelist if we're inside an existing slurm allocation)
        cmdfos[iproc]['nodelist'] = [corelist[iproc]]  # the downside to setting each proc's node list here is that each proc is stuck on that node for each restart (well, unless we decide to change it when we restart it)

# ----------------------------------------------------------------------------------------
def check_cmd(cmd, options=''):  # check for existence of <cmd> (this exists just because check_call() throws a 'no such file or directory' error, and people never figure out that that means the command isn't found)
    try:
        subprocess.check_call([cmd] + options, stdout=open('/dev/null'))
    except OSError:
        raise Exception('command \'%s\' not found in path (maybe not installed?)' % cmd)

# ----------------------------------------------------------------------------------------
def run_r(cmdlines, workdir, dryrun=False, print_time=None, extra_str='', return_out_err=False, debug=False):
    if not os.path.exists(workdir):
        raise Exception('workdir %s doesn\'t exist' % workdir)
    check_cmd('R', options=['--slave', '--version'])
    cmdfname = workdir + '/run.r'
    if debug:
        print '      r cmd lines:'
        print pad_lines('\n'.join(cmdlines))
    with open(cmdfname, 'w') as cmdfile:
        cmdfile.write('\n'.join(cmdlines) + '\n')
    retval = simplerun('R --slave -f %s' % cmdfname, return_out_err=return_out_err, print_time=print_time, extra_str=extra_str, dryrun=dryrun, debug=debug)
    os.remove(cmdfname)  # different sort of <cmdfname> to that in simplerun()
    if return_out_err:
        outstr, errstr = retval
        return outstr, errstr

# ----------------------------------------------------------------------------------------
def run_ete_script(sub_cmd, ete_path, return_for_cmdfos=False, tmpdir=None, dryrun=False, extra_str='', debug=True):  # ete3 requires its own python version, so we run as a subprocess
    prof_cmds = '' # ' -m cProfile -s tottime -o prof.out'
    # xvfb_err_str = '' # '-e %s' % XXX outdir + '/xvfb-err'  # tell xvfb-run to write its error to this file (rather than its default of /dev/null). This is only errors actually from xvfb-run, e.g. xauth stuff is broken
    if tmpdir is None:
        tmpdir = choose_random_subdir('/tmp/xvfb-run', make_dir=True)
    cmd = 'export TMPDIR=%s' % tmpdir
    cmd += ' && export PATH=%s:$PATH' % ete_path
    cmd += ' && %s/bin/xvfb-run -a python%s %s' % (get_partis_dir(), prof_cmds, sub_cmd)
    if return_for_cmdfos:
        return cmd, tmpdir
    else:
        if debug:
            itmp = cmd.rfind('&&')
            print '%s%s %s' % (extra_str, color('red', 'run'), '%s \\\n%s     %s' % (cmd[:itmp + 2], extra_str, cmd[itmp + 2:]))
        simplerun(cmd, shell=True, dryrun=dryrun, debug=False)
        os.rmdir(tmpdir)

# ----------------------------------------------------------------------------------------
def simplerun(cmd_str, shell=False, cmdfname=None, dryrun=False, return_out_err=False, print_time=None, extra_str='', logfname=None, debug=True):
    if cmdfname is not None:
        with open(cmdfname, 'w') as cmdfile:
            cmdfile.write(cmd_str)
        subprocess.check_call(['chmod', '+x', cmdfname])
        cmd_str = cmdfname

    if debug:
        print '%s%s %s' % (extra_str, color('red', 'run'), cmd_str)
    sys.stdout.flush()
    if dryrun:
        return '', '' if return_out_err else None
    if print_time is not None:
        start = time.time()

    if return_out_err:
        with tempfile.TemporaryFile() as fout, tempfile.TemporaryFile() as ferr:
            subprocess.check_call(cmd_str if shell else cmd_str.split(), env=os.environ, shell=shell, stdout=fout, stderr=ferr)
            fout.seek(0)
            ferr.seek(0)
            outstr = ''.join(fout.readlines())
            errstr = ''.join(ferr.readlines())
    else:
        if logfname is not None:  # write cmd_str to logfname, then redirect stdout to it as well
            if not os.path.exists(os.path.dirname(logfname)):
                os.makedirs(os.path.dirname(logfname))
            subprocess.check_call('echo %s >%s'%(cmd_str, logfname), shell=True)
            cmd_str = '%s >>%s' % (cmd_str, logfname)
            shell = True
        subprocess.check_call(cmd_str if shell else cmd_str.split(), env=os.environ, shell=shell)

    if cmdfname is not None:
        os.remove(cmdfname)
    if print_time is not None:
        print '      %s time: %.1f' % (print_time, time.time() - start)

    if return_out_err:
        return outstr, errstr

# ----------------------------------------------------------------------------------------
def memory_usage_fraction(debug=False):  # return fraction of total system memory that this process is using (as always with memory things, this is an approximation)
    if platform.system() != 'Linux':
        print '\n  note: utils.memory_usage_fraction() needs testing on platform \'%s\' to make sure unit conversions don\'t need changing' % platform.system()
    current_usage = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)  # kb
    total = float(psutil.virtual_memory().total) / 1000.  # returns bytes, then convert to kb
    if debug:
        print '  using %.0f / %.0f MB = %.4f' % (current_usage / 1000, total / 1000, current_usage / total)
    return current_usage / total

# ----------------------------------------------------------------------------------------
def auto_n_procs():  # for running on the local machine
    n_procs = multiprocessing.cpu_count()
    if n_procs > 10: # if it's a huge server, we probably shouldn't use all the cores
        n_procs = int(float(n_procs) / 2.)
    return n_procs

# ----------------------------------------------------------------------------------------
def limit_procs(cmdstr, n_max_procs=None, sleep_time=1, procs=None, debug=False):  # <sleep_time> is seconds
    if cmdstr is None:
        if procs is None:
            raise Exception('<cmdstr> should be a (string) fragment of the command that will show up in ps, e.g. \'bin/partis\'')
        else:
            def n_running_jobs():
                return [p.poll() for p in procs].count(None)
    else:
        def n_running_jobs():
            return int(subprocess.check_output('ps auxw | grep %s | grep -v grep | wc -l' % cmdstr, shell=True))
    if n_max_procs is None:
        n_max_procs = auto_n_procs()
    n_jobs = n_running_jobs()
    while n_jobs >= n_max_procs:
        if debug:
            print '%d (>=%d) running jobs' % (n_jobs, n_max_procs)
        time.sleep(sleep_time)
        n_jobs = n_running_jobs()

# ----------------------------------------------------------------------------------------
def run_proc_functions(procs, n_procs=None, debug=False):  # <procs> is a list of multiprocessing.Process objects
    if n_procs is None:
        n_procs = auto_n_procs()
    if debug:
        print '    running %d proc fcns with %d procs' % (len(procs), n_procs)
        sys.stdout.flush()
    while True:
        while len(procs) > 0 and len(multiprocessing.active_children()) < n_procs:
            procs[0].start()
            procs.pop(0)
        if len(multiprocessing.active_children()) == 0 and len(procs) == 0:
            break

# ----------------------------------------------------------------------------------------
def get_batch_system_str(batch_system, cmdfo, fout, ferr, batch_options):
    prestr = ''

    if batch_system == 'slurm':
        prestr += 'srun --export=ALL --nodes 1 --ntasks 1'  # --exclude=data/gizmod.txt'  # --export=ALL seems to be necessary so XDG_RUNTIME_DIR gets passed to the nodes
        if 'threads' in cmdfo:
            prestr += ' --cpus-per-task %d' % cmdfo['threads']
        if 'nodelist' in cmdfo:
            prestr += ' --nodelist ' + ','.join(cmdfo['nodelist'])
    elif batch_system == 'sge':
        prestr += 'qsub -sync y -b y -V -o ' + fout + ' -e ' + ferr
        fout = None
        ferr = None
    else:
        assert False

    if batch_options is not None:
        prestr += ' ' + batch_options

    return prestr, fout, ferr

# ----------------------------------------------------------------------------------------
def cycle_log_files(logfname, debug=False):  # move any existing log file to .0, .1, etc.
    if not os.path.exists(logfname):  # nothing to do
        return
    itmp = 0
    while os.path.exists('%s.%d'%(logfname, itmp)):
        itmp += 1
    if debug:
        print '  %s --> %s' % (logfname, '%s.%d'%(logfname, itmp))
    os.rename(logfname, '%s.%d'%(logfname, itmp))

# ----------------------------------------------------------------------------------------
def run_cmd(cmdfo, batch_system=None, batch_options=None, shell=False):
    cstr = cmdfo['cmd_str']  # don't want to modify the str in <cmdfo>
    fout = cmdfo['logdir'] + '/out'
    ferr = cmdfo['logdir'] + '/err'
    cycle_log_files(fout)
    cycle_log_files(ferr)

    if batch_system is not None:
        prestr, fout, ferr = get_batch_system_str(batch_system, cmdfo, fout, ferr, batch_options)
        cstr = prestr + ' ' + cstr

    if not os.path.exists(cmdfo['logdir']):
        os.makedirs(cmdfo['logdir'])

    proc = subprocess.Popen(cstr if shell else cstr.split(),
                            stdout=None if fout is None else open(fout, 'w'),
                            stderr=None if ferr is None else open(ferr, 'w'),
                            env=cmdfo.get('env'), shell=shell)
    return proc

# ----------------------------------------------------------------------------------------
# <cmdfos> list of dicts, each dict specifies how to run one process, entries:
cmdfo_required_keys = [
    'cmd_str',  #  actual command to run
    'outfname',  # output file resulting from 'cmd_str'. Used to determine if command completed successfully
    'workdir',  # either this or 'logdir' must be set. If <clean_on_success> is set, this directory is removed when finished. Also serves as default for 'logdir'. (ok this is kind of messy, this probably used to be used for more things)
]
cmdfo_defaults = {  # None means by default it's absent
    'logdir' : 'workdir',  # where to write stdout/stderr (written as the files 'out' and 'err'). If not set, they go in 'workdir' (I don't like this default, but there's way too much code that depends on it to change it now)
    'workfnames' : None,  # if <clean_on_success> is set, this list of files is deleted before removing 'workdir' upon successful completion
    'dbgfo' : None,  # dict to store info from bcrham stdout about how many viterbi/forward/etc. calculations it performed
    'env' : None,  # if set, passed to the env= keyword arg in Popen
    'nodelist' : None,  # list of slurm nodes to allow; do not use, only set automatically
    'threads' : None,  # slurm cpus per task
}

# ----------------------------------------------------------------------------------------
# notes:
#  - set sleep to False if your commands are going to run really really really quickly
#  - unlike everywhere else, <debug> is not a boolean, and is either None (swallow out, print err)), 'print' (print out and err), 'write' (write out and err to file called 'log' in logdir), or 'write:<log file name>' (same as 'write', but you set your own base name)
#  - if both <n_max_procs> and <proc_limit_str> are set, it uses limit_procs() (i.e. a ps call) to count the total number of <proc_limit_str> running on the machine; whereas if only <n_max_procs> is set, it counts only subprocesses that it is itself running
#  - debug: can be None (stdout mostly gets ignored), 'print' (printed), 'write' (written to file 'log' in logdir), or 'write:<logfname>' (same, but use <logfname>)
def run_cmds(cmdfos, shell=False, n_max_tries=None, clean_on_success=False, batch_system=None, batch_options=None, batch_config_fname=None,
             debug=None, ignore_stderr=False, sleep=True, n_max_procs=None, proc_limit_str=None, allow_failure=False):
    if len(cmdfos) == 0:
        raise Exception('zero length cmdfos')
    if n_max_tries is None:
        n_max_tries = 1 if batch_system is None else 3
    per_proc_sleep_time = 0.01 / max(1, len(cmdfos))

    # check cmdfos and set defaults
    if len(set(cmdfo_required_keys) - set(cmdfos[0])) > 0:
        raise Exception('missing required keys in cmdfos: %s' % ' '.join(set(cmdfo_required_keys) - set(cmdfos[0])))
    if len(set(cmdfos[0]) - set(cmdfo_required_keys) - set(cmdfo_defaults)) > 0:
        raise Exception('unexpected key in cmdfos: %s' % ' '.join(set(cmdfos[0]) - set(cmdfo_required_keys) - set(cmdfo_defaults)))
    for iproc in range(len(cmdfos)):  # ok this is way overcomplicated now that I'm no longer adding None ones by default, oh well
        for ckey, dval in cmdfo_defaults.items():
            if ckey not in cmdfos[iproc] and dval is not None:
                cmdfos[iproc][ckey] = cmdfos[iproc][dval] if dval in cmdfos[iproc] else None  # first bit is only used for using workdir as the logdir default a.t.m.

    if batch_system == 'slurm' and batch_config_fname is not None:
        set_slurm_nodelist(cmdfos, batch_config_fname)

    procs, n_tries_list = [], []
    for iproc in range(len(cmdfos)):
        procs += [run_cmd(cmdfos[iproc], batch_system=batch_system, batch_options=batch_options, shell=shell)]
        n_tries_list.append(1)
        if sleep:
            time.sleep(per_proc_sleep_time)
        if n_max_procs is not None:
            limit_procs(proc_limit_str, n_max_procs, procs=procs)  # NOTE now that I've added the <procs> arg, I should remove all the places where I'm using the old cmd str method (I mean, it works fine, but it's hackier/laggier, and in cases where several different parent procs are running a log of the same-named subprocs on the same machine, the old way will be wrong [i.e. limit_procs was originally intended as a global machine-wide limit, whereas in this fcn we usually call it wanting to set a specific number of subproces for this process])

    while procs.count(None) != len(procs):  # we set each proc to None when it finishes
        for iproc in range(len(cmdfos)):
            if procs[iproc] is None:  # already finished
                continue
            if procs[iproc].poll() is not None:  # it just finished
                status = finish_process(iproc, procs, n_tries_list[iproc], cmdfos[iproc], n_max_tries, dbgfo=cmdfos[iproc].get('dbgfo'), batch_system=batch_system, debug=debug, ignore_stderr=ignore_stderr, clean_on_success=clean_on_success, allow_failure=allow_failure)
                if status == 'restart':
                    procs[iproc] = run_cmd(cmdfos[iproc], batch_system=batch_system, batch_options=batch_options, shell=shell)
                    n_tries_list[iproc] += 1
        sys.stdout.flush()
        if sleep:
            time.sleep(per_proc_sleep_time)

# ----------------------------------------------------------------------------------------
def pad_lines(linestr, padwidth=8):
    lines = [padwidth * ' ' + l for l in linestr.split('\n')]
    return '\n'.join(lines)

# ----------------------------------------------------------------------------------------
def get_slurm_node(errfname):
    if not os.path.exists(errfname):
        return None

    jobid = None
    try:
        jobid = subprocess.check_output(['head', '-n1', errfname]).split()[2]
    except (subprocess.CalledProcessError, IndexError) as err:
        print err
        print '      couldn\'t get jobid from err file %s with contents:' % errfname
        subprocess.check_call(['cat', errfname])
        return None

    assert jobid is not None
    nodelist = None
    try:
        nodelist = subprocess.check_output(['squeue', '--job', jobid, '--states=all', '--format', '%N']).split()[1]
    except (subprocess.CalledProcessError, IndexError) as err:
        print err
        print '      couldn\'t get node list from jobid \'%s\'' % jobid
        return None

    assert nodelist is not None
    if ',' in nodelist:  # I think this is what it looks like if there's more than one, but I'm not checking
        raise Exception('multiple nodes in nodelist: \'%s\'' % nodelist)

    return nodelist

# ----------------------------------------------------------------------------------------
# deal with a process once it's finished (i.e. check if it failed, and tell the calling fcn to restart it if so)
def finish_process(iproc, procs, n_tried, cmdfo, n_max_tries, dbgfo=None, batch_system=None, debug=None, ignore_stderr=False, clean_on_success=False, allow_failure=False):
    procs[iproc].communicate()
    outfname = cmdfo['outfname']

    # success
    if procs[iproc].returncode == 0:
        if not os.path.exists(outfname):
            print '      proc %d succeeded but its output isn\'t there, so sleeping for a bit: %s' % (iproc, outfname)  # give a networked file system some time to catch up
            time.sleep(0.5)
        if os.path.exists(outfname):
            process_out_err(cmdfo['logdir'], extra_str='' if len(procs) == 1 else str(iproc), dbgfo=dbgfo, cmd_str=cmdfo['cmd_str'], debug=debug, ignore_stderr=ignore_stderr)
            procs[iproc] = None  # job succeeded
            if clean_on_success:  # this is newer than the rest of the fcn, so it's only actually used in one place, but it'd be nice if other places started using it eventually
                if cmdfo.get('workfnames') is not None:
                    for fn in [f for f in cmdfo['workfnames'] if os.path.exists(f)]:
                        os.remove(fn)
                if os.path.isdir(cmdfo['workdir']):
                    os.rmdir(cmdfo['workdir'])
            return 'ok'

    # handle failure
    print '    proc %d try %d' % (iproc, n_tried),
    if procs[iproc].returncode == 0 and not os.path.exists(outfname):  # don't really need both the clauses
        print 'succeeded but output is missing: %s' % outfname
    else:
        print 'failed with exit code %d, %s: %s' % (procs[iproc].returncode, 'but output exists' if os.path.exists(outfname) else 'and output is missing',  outfname)
    if batch_system == 'slurm':  # cmdfo['cmd_str'].split()[0] == 'srun' and
        if 'nodelist' in cmdfo:  # if we're doing everything from within an existing slurm allocation
            nodelist = cmdfo['nodelist']
        else:  # if, on the other hand, each process made its own allocation on the fly
            nodelist = get_slurm_node(cmdfo['logdir'] + '/err')
        if nodelist is not None:
            print '    failed on node %s' % nodelist
        # try:
        #     print '        sshing to %s' % nodelist
        #     outstr = check_output('ssh -o StrictHostKeyChecking=no ' + nodelist + ' ps -eo pcpu,pmem,rss,cputime:12,stime:7,user,args:100 --sort pmem | tail', shell=True)
        #     print pad_lines(outstr, padwidth=12)
        # except subprocess.CalledProcessError as err:
        #     print '        failed to ssh:'
        #     print err
    if os.path.exists(outfname + '.progress'):  # glomerator.cc is the only one that uses this at the moment
        print '        progress file (%s):' % (outfname + '.progress')
        print pad_lines(subprocess.check_output(['cat', outfname + '.progress']), padwidth=12)

    # ----------------------------------------------------------------------------------------
    def logfname(ltype):
        return cmdfo['logdir'] + '/' + ltype

    # ----------------------------------------------------------------------------------------
    def getlogstrs(logtypes=None):  # not actually using stdout at all, but maybe I should?
        if logtypes is None:
            logtypes = ['out', 'err']
        returnstr = []
        for ltype in logtypes:
            if os.path.exists(logfname(ltype)) and os.stat(logfname(ltype)).st_size > 0:
                returnstr += ['        std%s:           %s' % (ltype, logfname(ltype))]
                returnstr += [pad_lines(subprocess.check_output(['cat', logfname(ltype)]), padwidth=12)]
        return '\n'.join(returnstr)

    if n_tried < n_max_tries:
        print getlogstrs(['err'])
        print '      restarting proc %d' % iproc
        return 'restart'
    else:
        failstr = 'exceeded max number of tries (%d >= %d) for subprocess with command:\n        %s\n' % (n_tried, n_max_tries, cmdfo['cmd_str'])
        tmpstr = getlogstrs(['err'])
        if len(tmpstr.strip()) == 0:  # bppseqgen puts it in stdout, so we have to look there
            tmpstr += 'std out tail (err was empty):\n'
            tmpstr += '\n'.join(getlogstrs(['out']).split('\n')[-30:])
        failstr += tmpstr
        if allow_failure:
            print '      %s\n      not raising exception for failed process' % failstr
            procs[iproc] = None  # let it keep running any other processes
        else:
            raise Exception(failstr)

    return 'failed'

# ----------------------------------------------------------------------------------------
def process_out_err(logdir, extra_str='', dbgfo=None, cmd_str=None, debug=None, ignore_stderr=False):
    # NOTE something in this chain seems to block or truncate or some such nonsense if you make it too big
    err_strs_to_ignore = [
        'stty: standard input: Inappropriate ioctl for device',
        'queued and waiting for resources',
        'has been allocated resources',
        'srun: Required node not available (down, drained or reserved)',
        'GSL_RNG_TYPE=',
        'GSL_RNG_SEED=',
        '[ig_align] Read',
        '[ig_align] Aligned',
    ]
    def read_and_delete_file(fname):
        fstr = ''
        if os.stat(fname).st_size > 0:  # NOTE if <fname> doesn't exist, it probably means you have more than one process writing to the same log file
            ftmp = open(fname)
            fstr = ''.join(ftmp.readlines())
            ftmp.close()
        os.remove(fname)
        return fstr
    def skip_err_line(line):
        if len(line.strip()) == 0:
            return True
        for tstr in err_strs_to_ignore:
            if tstr in line:
                return True
        return False

    logstrs = {tstr : read_and_delete_file(logdir + '/' + tstr) for tstr in ['out', 'err']}

    err_str = []
    for line in logstrs['err'].split('\n'):
        if skip_err_line(line):
            continue
        err_str += [line]
    err_str = '\n'.join(err_str)

    if 'bcrham' in cmd_str:
        for line in logstrs['out'].split('\n'):  # print debug info related to --n-final-clusters/--min-largest-cluster-size force merging
            if 'force' in line:
                print '    %s %s' % (color('yellow', 'force info:'), line)

    if dbgfo is not None:  # keep track of how many vtb and fwd calculations the process made
        for header, variables in bcrham_dbgstrs['partition'].items():  # 'partition' is all of them, 'annotate' is a subset
            dbgfo[header] = {var : None for var in variables}
            theselines = [ln for ln in logstrs['out'].split('\n') if header + ':' in ln]
            if len(theselines) == 0:
                continue
            if len(theselines) > 1:
                raise Exception('too many lines with dbgfo for \'%s\' in:\nstdout:\n%s\nstderr:\n%s' % (header, logstrs['out'], logstrs['err']))
            words = theselines[0].split()
            for var in variables:  # convention: value corresponding to the string <var> is the word immediately vollowing <var>
                if var in words:
                    if words.count(var) > 1:
                        raise Exception('found multiple instances of variable \'%s\' in line \'%s\'' % (var, theselines[0]))
                    dbgfo[header][var] = float(words[words.index(var) + 1])

    if debug is None:
        if not ignore_stderr and len(err_str) > 0:
            print err_str
    elif len(err_str) + len(logstrs['out']) > 0:
        if debug == 'print':
            if extra_str != '':
                tmpcolor = 'red_bkg' if len(err_str + logstrs['out']) != len_excluding_colors(err_str + logstrs['out']) else None  # if there's color in the out/err strs, make the 'proc 0' str colored as well
                print '      --> %s' % color(tmpcolor, 'proc %s' % extra_str)
            print err_str + logstrs['out']
        elif 'write' in debug:
            if debug == 'write':
                logfile = logdir + '/log'
            else:
                assert debug[:6] == 'write:'
                logfile = logdir + '/' + debug.replace('write:', '')
            cycle_log_files(logfile)
            with open(logfile, 'w') as dbgfile:
                if cmd_str is not None:
                    dbgfile.write('%s %s\n' % (color('red', 'run'), cmd_str))  # NOTE duplicates code in datascripts/run.py
                dbgfile.write(err_str + logstrs['out'])
        else:
            assert False

# ----------------------------------------------------------------------------------------
def summarize_bcrham_dbgstrs(dbgfos, action):
    def defval(dbgcat):
        if dbgcat in bcrham_dbgstr_types[action]['sum']:
            return 0.
        elif dbgcat in bcrham_dbgstr_types[action]['same']:
            return None
        elif dbgcat in bcrham_dbgstr_types[action]['min-max']:
            return []
        else:
            assert False

    cache_read_inconsistency = False
    summaryfo = {dbgcat : {vtype : defval(dbgcat) for vtype in tlist} for dbgcat, tlist in bcrham_dbgstrs[action].items()}  # fill summaryfo with default/initial values
    for procfo in dbgfos:
        for dbgcat in bcrham_dbgstr_types[action]['same']:  # loop over lines in output for which every process should have the same values (e.g. cache-read)
            for vtype in bcrham_dbgstrs[action][dbgcat]:  # loop over values in that line (e.g. logprobs and naive-seqs)
                if summaryfo[dbgcat][vtype] is None:  # first one
                    summaryfo[dbgcat][vtype] = procfo[dbgcat][vtype]
                if procfo[dbgcat][vtype] != summaryfo[dbgcat][vtype]:  # make sure all subsequent ones are the same
                    cache_read_inconsistency = True
                    print '        %s bcrham procs had different \'%s\' \'%s\' info: %d vs %d' % (color('red', 'warning'), vtype, dbgcat, procfo[dbgcat][vtype], summaryfo[dbgcat][vtype])
        for dbgcat in bcrham_dbgstr_types[action]['sum']:  # lines for which we want to add up the values
            for vtype in bcrham_dbgstrs[action][dbgcat]:
                if procfo[dbgcat][vtype] is None:  # can't seem to replicate this, but it happened once
                    print '  %s none type dbg info read from subprocess (maybe the batch system made the subprocess print out something extra so it didn\'t parse correctly?)' % color('yellow', 'warning')
                else:
                    summaryfo[dbgcat][vtype] += procfo[dbgcat][vtype]
        for dbgcat in bcrham_dbgstr_types[action]['min-max']:  # lines for which we want to keep track of the smallest and largest values (e.g. time required)
            for vtype in bcrham_dbgstrs[action][dbgcat]:
                summaryfo[dbgcat][vtype].append(procfo[dbgcat][vtype])

    for dbgcat in bcrham_dbgstr_types[action]['min-max']:
        for vtype in bcrham_dbgstrs[action][dbgcat]:
            summaryfo[dbgcat][vtype] = min(summaryfo[dbgcat][vtype]), max(summaryfo[dbgcat][vtype])

    if cache_read_inconsistency:
        raise Exception('inconsistent cache reading information across processes (see above), probably due to file system issues')

    return summaryfo

# ----------------------------------------------------------------------------------------
def find_first_non_ambiguous_base(seq):
    """ return index of first non-ambiguous base """
    for ib in range(len(seq)):
        if seq[ib] not in all_ambiguous_bases:
            return ib
    assert False  # whole sequence was ambiguous... probably shouldn't get here

# ----------------------------------------------------------------------------------------
def find_last_non_ambiguous_base_plus_one(seq):
    for ib in range(len(seq) - 1, -1, -1):  # count backwards from the end
        if seq[ib] not in all_ambiguous_bases:  # find first non-ambiguous base
            return ib + 1  # add one for easy slicing

    assert False  # whole sequence was ambiguous... probably shouldn't get here

# ----------------------------------------------------------------------------------------
def remove_ambiguous_ends(seq):
    """ remove ambiguous bases from the left and right ends of <seq> """
    i_seq_start = find_first_non_ambiguous_base(seq)
    i_seq_end = find_last_non_ambiguous_base_plus_one(seq)
    return seq[i_seq_start : i_seq_end]

# ----------------------------------------------------------------------------------------
def split_clusters_by_cdr3(partition, sw_info, warn=False):
    new_partition = []
    all_cluster_splits = []
    for cluster in partition:
        cdr3_lengths = [sw_info[q]['cdr3_length'] for q in cluster]
        if len(set(cdr3_lengths)) == 1:
            new_partition.append(cluster)
        else:
            split_clusters = [list(group) for _, group in itertools.groupby(sorted(cluster, key=lambda q: sw_info[q]['cdr3_length']), key=lambda q: sw_info[q]['cdr3_length'])]  # TODO i think this should really be using group_seqs_by_value()
            for sclust in split_clusters:
                new_partition.append(sclust)
            all_cluster_splits.append((len(cluster), [len(c) for c in split_clusters]))
    if warn and len(all_cluster_splits) > 0:
        print '  %s split apart %d cluster%s that contained multiple cdr3 lengths (total clusters: %d --> %d)' % (color('yellow', 'warning'), len(all_cluster_splits), plural(len(all_cluster_splits)), len(partition), len(new_partition))
        print '      cluster splits: %s' % ', '.join(('%3d --> %s'%(cl, ' '.join(str(l) for l in spls))) for cl, spls in all_cluster_splits)
    return new_partition

# ----------------------------------------------------------------------------------------
def get_partition_from_annotation_list(annotation_list):
    return [copy.deepcopy(l['unique_ids']) for l in annotation_list]

# ----------------------------------------------------------------------------------------
def get_partition_from_reco_info(reco_info, ids=None):
    # Two modes:
    #  - if <ids> is None, it returns the actual, complete, true partition.
    #  - if <ids> is set, it groups them into the clusters dictated by the true partition in/implied by <reco_info> NOTE these are not, in general, complete clusters
    if ids is None:
        ids = reco_info.keys()
    def keyfunc(q):
        return reco_info[q]['reco_id']
    return [list(group) for _, group in itertools.groupby(sorted(ids, key=keyfunc), key=keyfunc)]  # sort 'em beforehand so all the ones with the same reco id are consecutive (if there are non-consecutive ones with the same reco id, it means there were independent events with the same rearrangment parameters)

# ----------------------------------------------------------------------------------------
def get_partition_from_str(partition_str):
    """ NOTE there's code in some other places that do the same thing """
    clusters = partition_str.split(';')
    partition = [cl.split(':') for cl in clusters]
    return partition

# ----------------------------------------------------------------------------------------
def get_str_from_partition(partition):
    """ NOTE there's code in some other places that do the same thing """
    clusters = [':'.join(cl) for cl in partition]
    partition_str = ';'.join(clusters)
    return partition_str

# ----------------------------------------------------------------------------------------
def get_cluster_ids(uids, partition):
    clids = {uid : [] for uid in uids}  # almost always list of length one with index (in <partition>) of the uid's cluster
    for iclust in range(len(partition)):
        for uid in partition[iclust]:
            if iclust not in clids[uid]:  # in case there's duplicates (from seed unique id)
                clids[uid].append(iclust)
    return clids

# ----------------------------------------------------------------------------------------
# return a new list of partitions that has no duplicate uids (choice as to which cluster gets to keep a duplicate id is entirely random [well, it's the first one that has it, so not uniform random, but you can't specify it])
def get_deduplicated_partitions(partitions, debug=False):  # not using this atm since i wrote it for use in clusterpath, but then ended up not needing it UPDATE now using it during paired clustering resolution, but maybe only temporarily
    if debug:
        print '    deduplicating %d partitions' % len(partitions)
    new_partitions = [[] for _ in partitions]
    for ipart in range(len(partitions)):
        if debug:
            print '      ipart %d: %d clusters: %d unique vs %d total uids (sum of cluster sizes)' % (ipart, len(partitions[ipart]), len(set(u for c in partitions[ipart] for u in c)), sum(len(c) for c in partitions[ipart]))
            duplicated_uids = set()
        previously_encountered_uids = set()
        for cluster in partitions[ipart]:
            new_cluster = copy.deepcopy(cluster)  # need to make sure not to modify the existing partitions
            new_cluster = list(set(new_cluster) - previously_encountered_uids)  # remove any uids that were in previous clusters (note that this will, of course, change the order of uids)
            previously_encountered_uids |= set(new_cluster)
            if len(new_cluster) > 0:
                new_partitions[ipart].append(new_cluster)
            if debug and len(new_cluster) < len(cluster):
                print '         removed %d uids from cluster of size %d' % (len(cluster) - len(new_cluster), len(cluster))
                duplicated_uids |= set(cluster) - set(new_cluster)
        if debug:
            print '      %d uids appeared more than once%s' % (len(duplicated_uids), (':  ' + ' '.join(duplicated_uids)) if len(duplicated_uids) < 10 else '')
    return new_partitions

# ----------------------------------------------------------------------------------------
def new_ccfs_that_need_better_names(partition, true_partition, reco_info=None, seed_unique_id=None, debug=False):
    if seed_unique_id is None:
        check_intersection_and_complement(partition, true_partition)
    if reco_info is None:  # build a dummy reco_info that just has reco ids
        def tkey(c): return ':'.join(c)
        chashes = {tkey(tc) : hash(tkey(tc)) for tc in true_partition}
        reco_info = {u : {'reco_id' : chashes[tkey(tc)]} for tc in true_partition for u in tc}
    reco_ids = {uid : reco_info[uid]['reco_id'] for cluster in partition for uid in cluster}  # speed optimization
    uids = set([uid for cluster in partition for uid in cluster])
    clids = get_cluster_ids(uids, partition)  # map of {uid : (index of cluster in <partition> in which that uid occurs)} (well, list of indices, in case there's duplicates)

    def get_clonal_fraction(uid, inferred_cluster):
        """ Return the fraction of seqs in <uid>'s inferred cluster which are really clonal. """
        n_clonal = 0
        for tmpid in inferred_cluster:  # NOTE this includes the case where tmpid equal to uid
            if reco_ids[tmpid] == reco_ids[uid]:  # reminder (see event.py) reco ids depend only on rearrangement parameters, i.e. two different rearrangement events with the same rearrangement parameters have the same reco id
                n_clonal += 1
        return float(n_clonal) / len(inferred_cluster)

    def get_fraction_present(inferred_cluster, true_cluster):
        """ Return the fraction of the true clonemates in <true_cluster> which appear in <inferred_cluster>. """
        n_present = 0
        for tmpid in true_cluster:  # NOTE this includes the case where tmpid equal to uid
            if tmpid in inferred_cluster:
                n_present += 1
        return float(n_present) / len(true_cluster)

    mean_clonal_fraction, mean_fraction_present = 0., 0.
    n_uids = 0
    for true_cluster in true_partition:
        if seed_unique_id is not None and seed_unique_id not in true_cluster:
            continue
        for uid in true_cluster:
            if seed_unique_id is not None and uid != seed_unique_id:
                continue
            if len(clids[uid]) != 1:  # this seems to only happen for earlier partitions (more than one proc) when seed_unique_id is set, since we pass seed_unique_id to all the subprocs. I.e. it's expected in these cases, and the ccfs don't make sense when a uid is in more than one cluster, since it's no longer a partition, so just return None, None
                if debug:
                    print '  %s found %s in multiple clusters while calculating ccfs (returning None, None)' % (color('red', 'warning'), uid)
                return None, None
            inferred_cluster = partition[clids[uid][0]]  # we only look at the first cluster in which it appears
            mean_clonal_fraction += get_clonal_fraction(uid, inferred_cluster)
            mean_fraction_present += get_fraction_present(inferred_cluster, true_cluster)
            n_uids += 1

    if n_uids > 1e6:
        raise Exception('you should start worrying about numerical precision if you\'re going to run on this many queries')

    return mean_clonal_fraction / n_uids, mean_fraction_present / n_uids

# ----------------------------------------------------------------------------------------
def correct_cluster_fractions(partition, true_partition, debug=False):
    # return new_ccfs_that_need_better_names(partition, true_partition, debug)  # hey, look, I'm a hack! Seriously, though, the new ccfs above are pretty similar, except they're per-sequence rather than per-cluster, so they don't get all scatterbrained and shit when a sample's only got a few clusters. Also, you still get partial credit for how good your cluster is, it's not just all-or-nothing.
    raise Exception('deprecated!')

    def find_clusters_with_ids(ids, partition):
        """ find all clusters in <partition> that contain at least one of <ids> """
        clusters = []
        for cluster in partition:
            for uid in ids:
                if uid in cluster:
                    clusters.append(cluster)
                    break
        return clusters

    check_intersection_and_complement(partition, true_partition)

    n_under_merged, n_over_merged = 0, 0
    for trueclust in true_partition:
        if debug:
            print ''
            print '   true %s' % (len(trueclust) if len(trueclust) > 15 else trueclust)
        infclusters = find_clusters_with_ids(trueclust, partition)  # list of inferred clusters that contain any ids from the true cluster
        if debug and len(infclusters) > 1:
            print '  infclusters %s' % infclusters
        assert len(infclusters) > 0
        under_merged = len(infclusters) > 1  # ids in true cluster are not all in the same inferred cluster
        over_merged = False  # at least one inferred cluster with an id in true cluster also contains an id not in true cluster
        for iclust in infclusters:
            if debug:
                print '   inferred %s' % (len(iclust) if len(iclust) > 15 else iclust)
            for uid in iclust:
                if uid not in trueclust:
                    over_merged = True
                    break
            if over_merged:
                break
        if debug:
            print '  under %s   over %s' % (under_merged, over_merged)
        if under_merged:
            n_under_merged += 1
        if over_merged:
            n_over_merged += 1

    under_frac = float(n_under_merged) / len(true_partition)
    over_frac = float(n_over_merged) / len(true_partition)
    if debug:
        print '  under %.2f   over %.2f' % (under_frac, over_frac)
    return (1. - under_frac, 1. - over_frac)

# ----------------------------------------------------------------------------------------
def partition_similarity_matrix(meth_a, meth_b, partition_a, partition_b, n_biggest_clusters, debug=False):
    """ Return matrix whose ij^th entry is the size of the intersection between <partition_a>'s i^th biggest cluster and <partition_b>'s j^th biggest """
    def intersection_size(cl_1, cl_2):
        isize = 0
        for uid in cl_1:
            if uid in cl_2:
                isize += 1
        return isize

    # n_biggest_clusters = 10
    def sort_within_clusters(part):
        for iclust in range(len(part)):
            part[iclust] = sorted(part[iclust])

    # a_clusters = sorted(partition_a, key=len, reverse=True)[ : n_biggest_clusters]  # i.e. the n biggest clusters
    # b_clusters = sorted(partition_b, key=len, reverse=True)[ : n_biggest_clusters]
    sort_within_clusters(partition_a)
    sort_within_clusters(partition_b)
    a_clusters = sorted(sorted(partition_a), key=len, reverse=True)[ : n_biggest_clusters]  # i.e. the n biggest clusters
    b_clusters = sorted(sorted(partition_b), key=len, reverse=True)[ : n_biggest_clusters]

    smatrix = []
    pair_info = []  # list of full pair info (e.g. [0.8, ick)
    max_pair_info = 5
    for clust_a in a_clusters:
        # if debug:
        #     print clust_a
        smatrix.append([])
        for clust_b in b_clusters:
            # norm_factor = 1.  # don't normalize
            norm_factor = 0.5 * (len(clust_a) + len(clust_b))  # mean size
            # norm_factor = min(len(clust_a), len(clust_b))  # smaller size
            intersection = intersection_size(clust_a, clust_b)
            isize = float(intersection) / norm_factor
            # if debug:
            #     print '    %.2f  %5d   %5d %5d' % (isize, intersection, len(clust_a), len(clust_b))
            if isize == 0.:
                isize = None
            smatrix[-1].append(isize)
            if isize is not None:
                if len(pair_info) < max_pair_info:
                    pair_info.append([intersection, [clust_a, clust_b]])
                    pair_info = sorted(pair_info, reverse=True)
                elif intersection > pair_info[-1][0]:
                    pair_info[-1] = [intersection, [clust_a, clust_b]]
                    pair_info = sorted(pair_info, reverse=True)

    if debug:
        print 'intersection     a_rank  b_rank'
        for it in pair_info:
            print '%-4d  %3d %3d   %s  %s' % (it[0], a_clusters.index(it[1][0]), b_clusters.index(it[1][1]), ':'.join(it[1][0]), ':'.join(it[1][1]))

    # with open('erick/' + meth_a + '_' + meth_b + '.csv', 'w') as csvfile:
    #     writer = csv.DictWriter(csvfile, ['a_meth', 'b_meth', 'intersection', 'a_rank', 'b_rank', 'a_cluster', 'b_cluster'])
    #     writer.writeheader()
    #     for it in pair_info:
    #         writer.writerow({'a_meth' : meth_a, 'b_meth' : meth_b,
    #                          'intersection' : it[0],
    #                          'a_rank' : a_clusters.index(it[1][0]), 'b_rank' : b_clusters.index(it[1][1]),
    #                          'a_cluster' : ':'.join(it[1][0]), 'b_cluster' : ':'.join(it[1][1])})

    a_cluster_lengths, b_cluster_lengths = [len(c) for c in a_clusters], [len(c) for c in b_clusters]
    return a_cluster_lengths, b_cluster_lengths, smatrix

# ----------------------------------------------------------------------------------------
def find_uid_in_partition(uid, partition):
    iclust, found = None, False
    for iclust in range(len(partition)):
        if uid in partition[iclust]:
            found = True
            break
    if found:
        return iclust
    else:
        raise Exception('couldn\'t find %s in %s\n' % (uid, partition))

# ----------------------------------------------------------------------------------------
def check_intersection_and_complement(part_a, part_b, only_warn=False, a_label='a', b_label='b'):
    """ make sure two partitions have identical uid lists """
    uids_a = set([uid for cluster in part_a for uid in cluster])
    uids_b = set([uid for cluster in part_b for uid in cluster])
    a_and_b = uids_a & uids_b
    a_not_b = uids_a - uids_b
    b_not_a = uids_b - uids_a
    if len(a_not_b) > 0 or len(b_not_a) > 0:  # NOTE this should probably also warn/pring if either of 'em has duplicate uids on their own
        failstr = '\'%s\' partition (%d total) and \'%s\' partition (%d total) don\'t have the same uids:   only %s %d    only %s %d    common %d' % (a_label, sum(len(c) for c in part_a), b_label, sum(len(c) for c in part_b), a_label, len(a_not_b), b_label, len(b_not_a), len(a_and_b))
        if only_warn:
            print '  %s %s' % (color('red', 'warning'), failstr)
        else:
            raise Exception(failstr)
    return a_and_b, a_not_b, b_not_a

# ----------------------------------------------------------------------------------------
def get_cluster_list_for_sklearn(part_a, part_b):
    # convert from partition format {cl_1 : [seq_a, seq_b], cl_2 : [seq_c]} to [cl_1, cl_1, cl_2]
    # NOTE this will be really slow for larger partitions

    # first make sure that <part_a> has every uid in <part_b> (the converse is checked below)
    for jclust in range(len(part_b)):
        for uid in part_b[jclust]:
            find_uid_in_partition(uid, part_a)  # raises exception if not found

    # then make the cluster lists
    clusts_a, clusts_b = [], []
    for iclust in range(len(part_a)):
        for uid in part_a[iclust]:
            clusts_a.append(iclust)
            clusts_b.append(find_uid_in_partition(uid, part_b))

    return clusts_a, clusts_b

# ----------------------------------------------------------------------------------------
def adjusted_mutual_information(partition_a, partition_b):
    return -1.  # not using it any more, and it's really slow
    # clusts_a, clusts_b = get_cluster_list_for_sklearn(partition_a, partition_b)
    # return sklearn.metrics.cluster.adjusted_mutual_info_score(clusts_a, clusts_b)

# ----------------------------------------------------------------------------------------
def add_missing_uids_as_singletons_to_inferred_partition(partition_with_missing_uids, true_partition=None, all_ids=None, debug=True):
    """ return a copy of <partition_with_missing_uids> which has had any uids which were missing inserted as singletons (i.e. uids which were in <true_partition>) """

    if true_partition is None:  # it's less confusing than the alternatives, I swear
        true_partition = [[uid, ] for uid in all_ids]

    partition_with_uids_added = copy.deepcopy(partition_with_missing_uids)
    missing_ids = []
    for cluster in true_partition:
        for uid in cluster:
            try:
                find_uid_in_partition(uid, partition_with_missing_uids)
            except:
                partition_with_uids_added.append([uid, ])
                missing_ids.append(uid)
    if debug:
        print '  %d (of %d) ids missing from partition (%s)' % (len(missing_ids), sum([len(c) for c in true_partition]), ' '.join(missing_ids))
    return partition_with_uids_added

# ----------------------------------------------------------------------------------------
def remove_missing_uids_from_true_partition(true_partition, partition_with_missing_uids, debug=True):
    """ return a copy of <true_partition> which has had any uids which do not occur in <partition_with_missing_uids> removed """
    true_partition_with_uids_removed = []
    missing_ids = []
    for cluster in true_partition:
        new_cluster = []
        for uid in cluster:
            try:
                find_uid_in_partition(uid, partition_with_missing_uids)
                new_cluster.append(uid)
            except:
                missing_ids.append(uid)
        if len(new_cluster) > 0:
            true_partition_with_uids_removed.append(new_cluster)
    if debug:
        print '  %d (of %d) ids missing from partition (%s)' % (len(missing_ids), sum([len(c) for c in true_partition]), ' '.join(missing_ids))
    return true_partition_with_uids_removed

# ----------------------------------------------------------------------------------------
def generate_incorrect_partition(true_partition, misassign_fraction, error_type, debug=False):
    """
    Generate an incorrect partition from <true_partition>.
    We accomplish this by removing <n_misassigned> seqs at random from their proper cluster, and putting each in either a
    cluster chosen at random from the non-proper clusters (<error_type> 'reassign') or in its own partition (<error_type> 'singleton').
    """
    # true_partition = [['b'], ['a', 'c', 'e', 'f'], ['d', 'g'], ['h', 'j']]
    # debug = True

    new_partition = copy.deepcopy(true_partition)
    nseqs = sum([len(c) for c in true_partition])
    n_misassigned = int(misassign_fraction * nseqs)
    if debug:
        print '  misassigning %d / %d seqs (should be clsoe to %.3f)' % (n_misassigned, nseqs, misassign_fraction)
        print '  before', new_partition

    uids = [uid for cluster in true_partition for uid in cluster]
    for _ in range(n_misassigned):
        uid = uids[random.randint(0, len(uids) - 1)]  # choose a uid to misassign (note that randint() is inclusive)
        uids.remove(uid)
        iclust = find_uid_in_partition(uid, new_partition)
        new_partition[iclust].remove(uid)  # remove it
        if [] in new_partition:
            new_partition.remove([])
        if error_type == 'singletons':  # put the sequence in a cluster by itself
            new_partition.append([uid, ])
            if debug:
                print '    %s: %d --> singleton' % (uid, iclust)
        elif error_type == 'reassign':  # choose a different cluster to add it to
            inewclust = iclust
            while inewclust == iclust:  # hm, this won't work if there's only one cluster in the partition. Oh, well, that probably won't happen
                inewclust = random.randint(0, len(new_partition) - 1)
            new_partition[inewclust].append(uid)
            if debug:
                print '    %s: %d --> %d' % (uid, iclust, inewclust)
        else:
            raise Exception('%s not among %s' % (error_type, 'singletons, reassign'))
    if debug:
        print '  after', new_partition
    return new_partition

# ----------------------------------------------------------------------------------------
def subset_files(uids, fnames, outdir, uid_header='Sequence ID', delimiter='\t', debug=False):
    """ rewrite csv files <fnames> to <outdir>, removing lines with uid not in <uids> """
    for fname in fnames:
        with open(fname) as infile:
            reader = csv.DictReader(infile, delimiter=delimiter)
            with open(outdir + '/' + os.path.basename(fname), 'w') as outfile:
                writer = csv.DictWriter(outfile, reader.fieldnames, delimiter=delimiter)
                writer.writeheader()
                for line in reader:
                    if line[uid_header] in uids:
                        writer.writerow(line)

# ----------------------------------------------------------------------------------------
def csv_to_fasta(infname, outfname=None, name_column='unique_ids', seq_column='input_seqs', n_max_lines=None, overwrite=True, remove_duplicates=False, debug=True):

    if not os.path.exists(infname):
        raise Exception('input file %s d.n.e.' % infname)
    if outfname is None:
        assert '.csv' in infname
        outfname = infname.replace('.csv', '.fa')
    if os.path.exists(outfname):
        if overwrite:
            if debug:
                print '  csv --> fasta: overwriting %s' % outfname
        else:
            if debug:
                print '  csv --> fasta: leaving existing outfile %s' % outfname
            return

    if '.csv' in infname:
        delimiter = ','
    elif '.tsv' in infname:
        delimiter = '\t'
    else:
        assert False

    uid_set = set()
    n_duplicate_ids = 0
    with open(infname) as infile:
        reader = csv.DictReader(infile, delimiter=delimiter)
        with open(outfname, 'w') as outfile:
            n_lines = 0
            for line in reader:
                if seq_column not in line:
                    raise Exception('specified <seq_column> \'%s\' not in line (keys in line: %s)' % (seq_column, ' '.join(line.keys())))
                if name_column is not None:
                    if name_column not in line:
                        raise Exception('specified <name_column> \'%s\' not in line (keys in line: %s)' % (name_column, ' '.join(line.keys())))
                    uid = line[name_column]
                else:
                    uid = str(abs(hash(line[seq_column])))
                if remove_duplicates:
                    if uid in uid_set:
                        n_duplicate_ids += 1
                        continue
                    uid_set.add(uid)
                n_lines += 1
                if n_max_lines is not None and n_lines > n_max_lines:
                    break
                outfile.write('>%s\n' % uid)
                outfile.write('%s\n' % line[seq_column])
    if debug and n_duplicate_ids > 0:
        print '   skipped %d / %d duplicate uids' % (n_duplicate_ids, len(uid_set))

# ----------------------------------------------------------------------------------------
def print_heapy(extrastr, heap):
    'Partition of a set of 1511530 objects. Total size = 188854824 bytes.'
    heapstr = heap.__str__()
    total = None
    for line in heapstr.split('\n'):
        if 'Total size' in line:
            total = int(line.split()[10])
    if total is None:
        print 'oops'
        print heapstr
        sys.exit()
    print 'mem total %.3f MB    %s' % (float(total) / 1e6, extrastr)

# ----------------------------------------------------------------------------------------
def auto_slurm(n_procs):
    """ Return true if we want to force slurm usage, e.g. if there's more processes than cores """

    def slurm_exists():
        try:
            fnull = open(os.devnull, 'w')
            subprocess.check_output(['which', 'srun'], stderr=fnull, close_fds=True)
            return True
        except subprocess.CalledProcessError:
            return False

    ncpu = multiprocessing.cpu_count()
    if n_procs > ncpu and slurm_exists():
        return True
    return False

# ----------------------------------------------------------------------------------------
def add_regional_alignments(glfo, aligned_gl_seqs, line, region, debug=False):
    if debug:
        print ' %s' % region

    aligned_seqs = [None for _ in range(len(line['unique_ids']))]
    for iseq in range(len(line['seqs'])):
        qr_seq = line[region + '_qr_seqs'][iseq]
        gl_seq = line[region + '_gl_seq']
        aligned_gl_seq = aligned_gl_seqs[region][line[region + '_gene']]
        if len(qr_seq) != len(gl_seq):
            if debug:
                print '    qr %d and gl %d seqs different lengths for %s, setting invalid' % (len(qr_seq), len(gl_seq), ' '.join(line['unique_ids']))
            line['invalid'] = True
            continue

        n_gaps = gap_len(aligned_gl_seq)
        if n_gaps == 0:
            if debug:
                print '   no gaps'
            aligned_seqs[iseq] = qr_seq
            continue

        if debug:
            print '   before alignment'
            print '      qr   ', qr_seq
            print '      gl   ', gl_seq
            print ' aligned gl', aligned_gl_seq

        # add dots for 5p and 3p deletions
        qr_seq = gap_chars[0] * line[region + '_5p_del'] + qr_seq + gap_chars[0] * line[region + '_3p_del']
        gl_seq = gap_chars[0] * line[region + '_5p_del'] + gl_seq + gap_chars[0] * line[region + '_3p_del']

        if len(aligned_gl_seq) - n_gaps != len(gl_seq):
            if debug:
                print '    aligned germline seq without gaps (%d - %d = %d) not the same length as unaligned gl/qr seqs %d' % (len(aligned_gl_seq), n_gaps, len(aligned_gl_seq) - n_gaps, len(gl_seq))
            line['invalid'] = True
            continue

        qr_seq = list(qr_seq)
        gl_seq = list(gl_seq)
        for ibase in range(len(aligned_gl_seq)):
            if aligned_gl_seq[ibase] in gap_chars:  # add gap to the qr and gl seq lists
                qr_seq.insert(ibase, gap_chars[0])
                gl_seq.insert(ibase, gap_chars[0])
            elif gl_seq[ibase] == aligned_gl_seq[ibase] or gl_seq[ibase] in gap_chars:  # latter is 5p or 3p deletion that we filled in above
                pass  # all is well
            else:  # all is not well, don't know why
                line['invalid'] = True
                break
        if line['invalid']:
            if debug:
                print '    unknown error during alignment process'
            continue
        qr_seq = ''.join(qr_seq)
        gl_seq = ''.join(gl_seq)

        if debug:
            print '   after alignment'
            print '      qr   ', qr_seq
            print '      gl   ', gl_seq
            print ' aligned gl', aligned_gl_seq

        if len(qr_seq) != len(gl_seq) or len(qr_seq) != len(aligned_gl_seq):  # I don't think this is really possible as currently written
            if debug:
                print '    lengths qr %d gl %d and aligned gl %d not all the same after alignment' % (len(qr_seq), len(gl_seq), len(aligned_gl_seq))
            line['invalid'] = True
            continue

        aligned_seqs[iseq] = qr_seq

    if line['invalid']:
        print '%s failed adding alignment info for %s' % (color('red', 'error'),' '.join(line['unique_ids']))  # will print more than once if it doesn't fail on the last region
        aligned_seqs = [None for _ in range(len(line['seqs']))]

    line['aligned_' + region + '_seqs'] = aligned_seqs

# ----------------------------------------------------------------------------------------
def add_alignments(glfo, aligned_gl_seqs, line, debug=False):
    for region in regions:
        add_regional_alignments(glfo, aligned_gl_seqs, line, region, debug)

# ----------------------------------------------------------------------------------------
def intexterpolate(x1, y1, x2, y2, x):
    """ interpolate/extrapolate linearly based on two points in 2-space, returning y-value corresponding to <x> """
    m = (y2 - y1) / (x2 - x1)
    b = 0.5 * (y1 + y2 - m*(x1 + x2))
    # if debug:
    #     for x in [x1, x2]:
    #         print '%f x + %f = %f' % (m, b, m*x + b)
    return m * x + b

# ----------------------------------------------------------------------------------------
def get_naive_hamming_bounds(partition_method, parameter_dir=None, overall_mute_freq=None):  # parameterize the relationship between mutation frequency and naive sequence inaccuracy
    if parameter_dir is not None:
        assert overall_mute_freq is None
        from hist import Hist
        mutehist = Hist(fname=parameter_dir + '/all-mean-mute-freqs.csv')
        mute_freq = mutehist.get_mean(ignore_overflows=True)  # should I not ignore overflows here?
    else:
        assert overall_mute_freq is not None
        mute_freq = overall_mute_freq

    # just use a line based on two points (mute_freq, threshold)
    x1, x2 = 0.05, 0.2  # 0.5x, 3x (for 10 leaves)

    if partition_method == 'naive-hamming':  # set lo and hi to the same thing, so we don't use log prob ratios, i.e. merge if less than this, don't merge if greater than this
        y1, y2 = 0.035, 0.06
        lo = intexterpolate(x1, y1, x2, y2, mute_freq)
        hi = lo
    elif partition_method == 'naive-vsearch':  # set lo and hi to the same thing, so we don't use log prob ratios, i.e. merge if less than this, don't merge if greater than this
        y1, y2 = 0.02, 0.05
        lo = intexterpolate(x1, y1, x2, y2, mute_freq)
        hi = lo
    elif partition_method == 'likelihood':  # these should almost never merge non-clonal sequences or split clonal ones, i.e. they're appropriate for naive hamming preclustering if you're going to then run the full likelihood (i.e. anything less than lo is almost certainly clonal, anything greater than hi is almost certainly not)
        y1, y2 = 0.015, 0.015  # would be nice to get better numbers for this
        lo = intexterpolate(x1, y1, x2, y2, mute_freq)  # ...and never merge 'em if it's bigger than this
        y1, y2 = 0.08, 0.15
        hi = intexterpolate(x1, y1, x2, y2, mute_freq)  # ...and never merge 'em if it's bigger than this
    else:
        assert False

    return lo, hi

# ----------------------------------------------------------------------------------------
def find_genes_that_have_hmms(parameter_dir):
    yamels = glob.glob(parameter_dir + '/hmms/*.yaml')
    if len(yamels) == 0:
        raise Exception('no yamels in %s' % parameter_dir + '/hmms')

    genes = []
    for yamel in yamels:
        gene = unsanitize_name(os.path.basename(yamel).replace('.yaml', ''))
        genes.append(gene)

    return genes

# ----------------------------------------------------------------------------------------
def choose_seed_unique_id(simfname, seed_cluster_size_low, seed_cluster_size_high, iseed=None, n_max_queries=-1, debug=True):
    _, annotation_list, _ = read_output(simfname, n_max_queries=n_max_queries, dont_add_implicit_info=True)
    true_partition = [l['unique_ids'] for l in annotation_list]

    nth_seed = 0  # don't always take the first one we find
    for cluster in true_partition:
        if len(cluster) < seed_cluster_size_low or len(cluster) > seed_cluster_size_high:
            continue
        if iseed is not None and int(iseed) > nth_seed:
            nth_seed += 1
            continue
        if debug:
            print '    chose seed %s in cluster %s with size %d' % (cluster[0], reco_info[cluster[0]]['reco_id'], len(cluster))
        return cluster[0], len(cluster)  # arbitrarily use the first member of the cluster as the seed

    raise Exception('couldn\'t find seed in cluster between size %d and %d' % (seed_cluster_size_low, seed_cluster_size_high))

# ----------------------------------------------------------------------------------------
# Takes two logd values and adds them together, i.e. takes (log a, log b) --> log a+b
# i.e. a *or* b
def add_in_log_space(first, second):
    if first == -float('inf'):
        return second
    elif second == -float('inf'):
        return first
    elif first > second:
        return first + math.log(1 + math.exp(second - first))
    else:
        return second + math.log(1 + math.exp(first - second))

# ----------------------------------------------------------------------------------------
def non_none(vlist):  # return the first non-None value in vlist (there are many, many places where i could go back and use this) [this avoids hard-to-read if/else statements that require writing the first val twice]
    for val in vlist:
        if val is not None:
            return val

# ----------------------------------------------------------------------------------------
def get_val_from_arglist(clist, argstr):
    if argstr not in clist:
        raise Exception('could\'t find %s in clist %s' % (argstr, clist))
    if clist.index(argstr) == len(clist) - 1:
        raise Exception('no argument for %s in %s' % (argstr, clist))
    val = clist[clist.index(argstr) + 1]
    if val[:2] == '--':
        raise Exception('no value for %s in %s (next word is %s)' % (argstr, clist, val))
    return val

# ----------------------------------------------------------------------------------------
def remove_from_arglist(clist, argstr, has_arg=False):
    if argstr not in clist:
        return
    if clist.count(argstr) > 1:
        raise Exception('multiple occurrences of argstr \'%s\' in cmd: %s' % (argstr, ' '.join(clist)))
    if has_arg:
        clist.pop(clist.index(argstr) + 1)
    clist.remove(argstr)

# ----------------------------------------------------------------------------------------
def replace_in_arglist(clist, argstr, replace_with, insert_after=None):  # or add it if it isn't already there
    if argstr not in clist:
        if insert_after is None or insert_after not in clist:  # just append it
            clist.append(argstr)
            clist.append(replace_with)
        else:  # insert after the arg <insert_after>
            insert_in_arglist(clist, [argstr, replace_with], insert_after, has_arg=True)
    else:
        if clist.count(argstr) > 1:
            raise Exception('multiple occurrences of argstr \'%s\' in cmd: %s' % (argstr, ' '.join(clist)))
        clist[clist.index(argstr) + 1] = replace_with

# ----------------------------------------------------------------------------------------
def insert_in_arglist(clist, new_arg_strs, argstr, has_arg=False, before=False):  # insert list new_arg_strs after/before argstr (and, if has_arg, after argstr's argument)
    i_insert = clist.index(argstr) + (2 if has_arg else 1)
    clist[i_insert : i_insert] = new_arg_strs

# ----------------------------------------------------------------------------------------
def kbound_str(kbounds):
    return_str = []
    for region in ['v', 'd']:
        rkb = kbounds[region]
        return_str.append('k_%s %d' % (region, rkb['best']))
        if 'min' in rkb and 'max' in rkb:
            return_str.append(' [%s-%s)' % (str(rkb.get('min', ' ')), str(rkb.get('max', ' '))))
        return_str.append('  ')
    return ''.join(return_str).strip()

# ----------------------------------------------------------------------------------------
def split_partition_with_criterion(partition, criterion_fcn):  # this would probably be faster if I used the itertools stuff from collapse_naive_seqs()
    true_cluster_indices = [ic for ic in range(len(partition)) if criterion_fcn(partition[ic])]  # indices of clusters for which <criterion_fcn()> is true
    true_clusters = [partition[ic] for ic in true_cluster_indices]
    false_clusters = [partition[ic] for ic in range(len(partition)) if ic not in true_cluster_indices]
    return true_clusters, false_clusters

# ----------------------------------------------------------------------------------------
def group_seqs_by_value(queries, keyfunc):  # don't have to be related seqs at all, only requirement is that the things in the iterable <queries> have to be valid arguments to <keyfunc()>
    return [list(group) for _, group in itertools.groupby(sorted(queries, key=keyfunc), key=keyfunc)]

# ----------------------------------------------------------------------------------------
def collapse_naive_seqs(swfo, queries=None, split_by_cdr3=False, debug=None):  # <split_by_cdr3> is only needed when we're getting synthetic sw info that's a mishmash of hmm and sw annotations
    start = time.time()
    if queries is None:
        queries = swfo['queries']  # don't modify this

    def keyfunc(q):  # while this is no longer happening before fwk insertion trimming (which was bad), it is still happening on N-padded sequences, which should be kept in mind
        if split_by_cdr3:
            return swfo[q]['cdr3_length'], swfo[q]['naive_seq']
        else:
            return swfo[q]['naive_seq']

    partition = group_seqs_by_value(queries, keyfunc)

    if debug:
        print '   collapsed %d queries into %d cluster%s with identical naive seqs (%.1f sec)' % (len(queries), len(partition), plural(len(partition)), time.time() - start)

    return partition

# ----------------------------------------------------------------------------------------
def collapse_naive_seqs_with_hashes(naive_seq_list, sw_info):  # this version is (atm) only used for naive vsearch clustering
    naive_seq_map = {}  # X[cdr3][hash(naive_seq)] : naive_seq
    naive_seq_hashes = {}  # X[hash(naive_seq)] : [uid1, uid2, uid3...]
    for uid, naive_seq in naive_seq_list:
        hashstr = str(hash(naive_seq))
        if hashstr not in naive_seq_hashes:  # first sequence that has this naive
            cdr3_length = sw_info[uid]['cdr3_length']
            if cdr3_length not in naive_seq_map:
                naive_seq_map[cdr3_length] = {}
            naive_seq_map[cdr3_length][hashstr] = naive_seq  # i.e. vsearch gets a hash of the naive seq (which maps to a list of uids with that naive sequence) instead of the uid
            naive_seq_hashes[hashstr] = []
        naive_seq_hashes[hashstr].append(uid)
    print '        collapsed %d sequences into %d unique naive sequences' % (len(naive_seq_list), len(naive_seq_hashes))
    return naive_seq_map, naive_seq_hashes

# ----------------------------------------------------------------------------------------
def write_fasta(fname, seqfos, name_key='name', seq_key='seq'):  # should have written this a while ago -- there's tons of places where I could use this instead of writing it by hand, but I'm not going to hunt them all down now
    if not os.path.isdir(os.path.dirname(fname)):
        os.makedirs(os.path.dirname(fname))
    with open(fname, 'w') as seqfile:
        for sfo in seqfos:
            seqfile.write('>%s\n%s\n' % (sfo[name_key], sfo[seq_key]))

# ----------------------------------------------------------------------------------------
def read_fastx(fname, name_key='name', seq_key='seq', add_info=True, dont_split_infostrs=False, sanitize_uids=False, sanitize_seqs=False, queries=None, n_max_queries=-1, istartstop=None, ftype=None, n_random_queries=None):
    if ftype is None:
        suffix = getsuffix(fname)
        if suffix == '.fa' or suffix == '.fasta':
            ftype = 'fa'
        elif suffix == '.fq' or suffix == '.fastq':
            ftype = 'fq'
        else:
            raise Exception('unhandled file type: %s' % suffix)

    finfo = []
    iline = -1  # index of the query/seq that we're currently reading in the fasta
    n_fasta_queries = 0  # number of queries so far added to <finfo> (I guess I could just use len(finfo) at this point)
    missing_queries = set(queries) if queries is not None else None
    already_printed_forbidden_character_warning = False
    with open(fname) as fastafile:
        startpos = None
        while True:
            if startpos is not None:  # rewind since the last time through we had to look to see when the next header line appeared
                fastafile.seek(startpos)
            headline = fastafile.readline()
            if not headline:
                break
            if headline.strip() == '':  # skip a blank line
                headline = fastafile.readline()

            if ftype == 'fa':
                if headline[0] != '>':
                    raise Exception('invalid fasta header line in %s:\n    %s' % (fname, headline))
                headline = headline.lstrip('>')

                seqlines = []
                nextline = fastafile.readline()
                while True:
                    if not nextline:
                        break
                    if nextline[0] == '>':
                        break
                    else:
                        startpos = fastafile.tell()  # i.e. very line that doesn't begin with '>' increments <startpos>
                    seqlines.append(nextline)
                    nextline = fastafile.readline()
                seqline = ''.join([l.strip() for l in seqlines]) if len(seqlines) > 0 else None
            elif ftype == 'fq':
                if headline[0] != '@':
                    raise Exception('invalid fastq header line in %s:\n    %s' % (fname, headline))
                headline = headline.lstrip('@')

                seqline = fastafile.readline()  # NOTE .fq with multi-line entries isn't supported, since delimiter characters are allowed to occur within the quality string
                plusline = fastafile.readline().strip()
                if plusline[0] != '+':
                    raise Exception('invalid fastq quality header in %s:\n    %s' % (fname, plusline))
                qualityline = fastafile.readline()
            else:
                raise Exception('unhandled ftype %s' % ftype)

            if not seqline:
                break

            iline += 1
            if istartstop is not None:
                if iline < istartstop[0]:
                    continue
                elif iline >= istartstop[1]:
                    continue

            if dont_split_infostrs:  # if this is set, we let the calling fcn handle all the infostr parsing (e.g. for imgt germline fasta files)
                infostrs = headline
                uid = infostrs
            else:  # but by default, we split by everything that could be a separator, which isn't really ideal, but we're reading way too many different kinds of fasta files at this point to change the default
                if ';' in headline and '=' in headline:  # HOLY SHIT PEOPLE DON"T PUT YOUR META INFO IN YOUR FASTA FILES
                    infostrs = [s1.split('=') for s1 in headline.strip().split(';')]
                    uid = infostrs[0][0]
                    infostrs = dict(s for s in infostrs if len(s) == 2)
                else:
                    infostrs = [s3.strip() for s1 in headline.split(' ') for s2 in s1.split('\t') for s3 in s2.split('|')]  # NOTE the uid is left untranslated in here
                    uid = infostrs[0]
            if sanitize_uids and any(fc in uid for fc in forbidden_characters):
                if not already_printed_forbidden_character_warning:
                    print '  %s: found a forbidden character (one of %s) in sequence id \'%s\'. This means we\'ll be replacing each of these forbidden characters with a single letter from their name (in this case %s). If this will cause problems you should replace the characters with something else beforehand. You may also be able to fix it by setting --parse-fasta-info.' % (color('yellow', 'warning'), ' '.join(["'" + fc + "'" for fc in forbidden_characters]), uid, uid.translate(forbidden_character_translations))
                    already_printed_forbidden_character_warning = True
                uid = uid.translate(forbidden_character_translations)

            if queries is not None:
                if uid not in queries:
                    continue
                missing_queries.remove(uid)

            seqfo = {name_key : uid, seq_key : seqline.strip().upper()}
            if add_info:
                seqfo['infostrs'] = infostrs
            if sanitize_seqs:
                seqfo[seq_key] = seqfo[seq_key].translate(ambig_translations)
                if any(c not in alphabet for c in seqfo[seq_key]):
                    unexpected_chars = set([ch for ch in seqfo[seq_key] if ch not in alphabet])
                    raise Exception('unexpected character%s %s (not among %s) in input sequence with id %s:\n  %s' % (plural(len(unexpected_chars)), ', '.join([('\'%s\'' % ch) for ch in unexpected_chars]), alphabet, seqfo[name_key], seqfo[seq_key]))
            finfo.append(seqfo)

            n_fasta_queries += 1
            if n_max_queries > 0 and n_fasta_queries >= n_max_queries:
                break
            if queries is not None and len(missing_queries) == 0:
                break

    if n_random_queries is not None:
        finfo = numpy.random.choice(finfo, n_random_queries, replace=False)

    return finfo

# ----------------------------------------------------------------------------------------
def output_exists(args, outfname, outlabel=None, offset=None, debug=True):
    outlabel = '' if outlabel is None else ('%s ' % outlabel)
    if offset is None: offset = 22  # weird default setting method so we can call it also with the fcn below
    if os.path.exists(outfname):
        if os.stat(outfname).st_size == 0:
            if debug:
                print '%sdeleting zero length %s' % (offset * ' ', outfname)
            os.remove(outfname)
            return False
        elif args.overwrite:
            if debug:
                print '%soverwriting %s%s' % (offset * ' ', outlabel, outfname)
            if os.path.isdir(outfname):
                raise Exception('output %s is a directory, rm it by hand' % outfname)
            else:
                os.remove(outfname)
            return False
        else:
            if debug:
                print '%s%soutput exists, skipping (%s)' % (offset * ' ', outlabel, outfname)
            return True
    else:
        return False

# ----------------------------------------------------------------------------------------
def all_outputs_exist(args, outfnames, outlabel=None, offset=None, debug=True):
    o_exist_list = [output_exists(args, ofn, outlabel=outlabel, offset=offset, debug=debug) for ofn in outfnames]
    return o_exist_list.count(True) == len(o_exist_list)

# ----------------------------------------------------------------------------------------
def getprefix(fname):  # basename before the dot
    if len(os.path.splitext(fname)) != 2:
        raise Exception('couldn\'t split %s into two pieces using dot' % fname)
    return os.path.splitext(fname)[0]

# ----------------------------------------------------------------------------------------
def getsuffix(fname):  # suffix, including the dot
    if len(os.path.splitext(fname)) != 2:
        raise Exception('couldn\'t split %s into two pieces using dot' % fname)
    return os.path.splitext(fname)[1]

# ----------------------------------------------------------------------------------------
def replace_suffix(fname, new_suffix):
    return fname.replace(getsuffix(fname), new_suffix)

# ----------------------------------------------------------------------------------------
def insert_before_suffix(insert_str, fname):
    return fname.replace(getsuffix(fname), '%s%s' % (insert_str, getsuffix(fname)))

# ----------------------------------------------------------------------------------------
def read_vsearch_cluster_file(fname):
    id_clusters = {}
    with open(fname) as clusterfile:
        reader = csv.DictReader(clusterfile, fieldnames=['type', 'cluster_id', '3', '4', '5', '6', '7', 'crap', 'query', 'morecrap'], delimiter='\t')
        for line in reader:
            if line['type'] == 'C':  # some lines are a cluster, and some are a query sequence. Skip the cluster ones.
                continue
            cluster_id = int(line['cluster_id'])
            if cluster_id not in id_clusters:
                id_clusters[cluster_id] = []
            uid = line['query']
            id_clusters[cluster_id].append(uid)
    partition = id_clusters.values()
    return partition

# ----------------------------------------------------------------------------------------
def read_vsearch_search_file(fname, userfields, seqdict, glfo, region, get_annotations=False, debug=False):
    def get_mutation_info(query, matchfo, indelfo):
        tmpgl = glfo['seqs'][region][matchfo['gene']][matchfo['glbounds'][0] : matchfo['glbounds'][1]]
        if indelutils.has_indels(indelfo):
            tmpqr = indelfo['reversed_seq'][matchfo['qrbounds'][0] : matchfo['qrbounds'][1] - indelutils.net_length(indelfo)]
        else:
            tmpqr = seqdict[query][matchfo['qrbounds'][0] : matchfo['qrbounds'][1]]
        # color_mutants(tmpgl, tmpqr, print_result=True, align=True)
        return hamming_distance(tmpgl, tmpqr, return_len_excluding_ambig=True, return_mutated_positions=True)

    # first we add every match (i.e. gene) for each query
    query_info = {}
    with open(fname) as alnfile:
        reader = csv.DictReader(alnfile, fieldnames=userfields, delimiter='\t')  # NOTE start/end positions are 1-indexed
        for line in reader:  # NOTE similarity to waterer.read_query()
            if line['query'] not in query_info:  # note that a surprisingly large number of targets give the same score, and you seem to get a little closer to what sw does if you sort alphabetically, but in the end it doesn't/shouldn't matter
                query_info[line['query']] = []
            query_info[line['query']].append({
                'ids' : int(line['ids']),
                'gene' : line['target'],
                'cigar' : line['caln'],
                'qrbounds' : (int(line['qilo']) - 1, int(line['qihi'])),
                'glbounds' : (int(line['tilo']) - 1, int(line['tihi'])),
            })

    # then we throw out all the matches (genes) that have id/score lower than the best one
    failed_queries = list(set(seqdict) - set(query_info))
    for query in query_info:
        if len(query_info[query]) == 0:
            print '%s zero vsearch matches for query %s' % (color('yellow', 'warning'), query)
            del query_info[query]  # uh... need to handle failures better than this
            failed_queries.append(query)
            continue
        query_info[query] = sorted(query_info[query], key=lambda d: d['ids'], reverse=True)  # sort the list of matches by decreasing score
        best_score = query_info[query][0]['ids']
        query_info[query] = [qinfo for qinfo in query_info[query] if qinfo['ids'] == best_score]  # keep all the matches that have the same score as the best match

    # then count up how many matches there were for each gene over all the sequences (to account for multiple matches with the same score, the count is not an integer)
    gene_counts = {}
    for query in query_info:
        counts_per_match = 1. / len(query_info[query])  # e.g. if there's four matches with the same score, give 'em each 0.25 counts
        for qinfo in query_info[query]:
            if qinfo['gene'] not in gene_counts:
                gene_counts[qinfo['gene']] = 0.
            gene_counts[qinfo['gene']] += counts_per_match

    annotations = OrderedDict()  # NOTE this is *not* a complete vdj annotation, it's just the info we have for an alignment to one region (presumably v)
    imatch = 0  # they all have the same score at this point, so just take the first one
    if get_annotations:  # it probably wouldn't really be much slower to just always do this
        for query in query_info:
            matchfo = query_info[query][imatch]
            v_indelfo = indelutils.get_indelfo_from_cigar(matchfo['cigar'], seqdict[query], matchfo['qrbounds'], glfo['seqs'][region][matchfo['gene']], matchfo['glbounds'], {'v' : matchfo['gene']}, vsearch_conventions=True, uid=query)
            n_mutations, len_excluding_ambig, mutated_positions = get_mutation_info(query, matchfo, v_indelfo)  # not sure this needs to just be the v_indelfo, but I'm leaving it that way for now
            combined_indelfo = indelutils.get_empty_indel()
            if indelutils.has_indels(v_indelfo):
                # huh, it actually works fine with zero-length d and j matches, so I don't need this any more
                # # arbitrarily give the d one base, and the j the rest of the sequence (I think they shouldn't affect anything as long as there's no d or j indels here)
                # if matchfo['qrbounds'][1] <= len(seqdict[query]) - 2:  # if we've got room to give 1 base to d and 1 base to j
                #     d_start = matchfo['qrbounds'][1]
                # else:  # ...but if we don't, then truncate the v match
                #     d_start = len(seqdict[query]) - 2
                # j_start = d_start + 1
                # tmpbounds = {
                #     'v' : (matchfo['qrbounds'][0], d_start),
                #     'd' : (d_start, j_start),
                #     'j' : (j_start, len(seqdict[query])),
                # }
                tmpbounds = {  # add zero-length d and j matches
                    'v' : matchfo['qrbounds'],
                    'd' : (matchfo['qrbounds'][1], matchfo['qrbounds'][1]),
                    'j' : (matchfo['qrbounds'][1], matchfo['qrbounds'][1]),
                }
                combined_indelfo = indelutils.combine_indels({'v' : v_indelfo}, seqdict[query], tmpbounds)
            annotations[query] = {
                region + '_gene' : matchfo['gene'],  # only works for v now, though
                'score' : matchfo['ids'],
                'n_' + region + '_mutations' : n_mutations,
                region + '_mut_freq' : float(n_mutations) / len_excluding_ambig,
                region + '_mutated_positions' : mutated_positions,
                'qrbounds' : {region : matchfo['qrbounds']},
                'glbounds' : {region : matchfo['glbounds']},
                'indelfo' : combined_indelfo,
            }

    return {'gene-counts' : gene_counts, 'annotations' : annotations, 'failures' : failed_queries}

# ----------------------------------------------------------------------------------------
# ok this sucks, but the original function below is used in a bunch of places that pass in a dict of seqs, and i don't want to mess with them since they're complicated, but now i also want it to be able to run on inputs with duplicate sequence ids
def run_vsearch_with_duplicate_uids(action, seqlist, workdir, threshold, **kwargs):
    # NOTE this is weird but necessary basically because in the normal partis workflows input always goes through seqfileopener, which renames duplicates, but now i want to be able to run this vsearch stuff without that (for bin/split-loci.py), which has .fa input files that i want to allow to have duplicates
    def get_trid(uid, seq):
        return '%s-DUP-%d' % (uid, abs(hash(seq)))
    seqdict = collections.OrderedDict()  # doesn't really need to be ordered here, but oh well
    for sfo in seqlist:
        uid = get_trid(sfo['name'], sfo['seq'])
        if uid in seqdict:
            raise Exception('can\'t handle multiple entries with both sequence and uid the same')
        seqdict[uid] = sfo['seq']
    returnfo = run_vsearch(action, seqdict, workdir, threshold, **kwargs)
    if set(returnfo) != set(['gene-counts', 'annotations', 'failures']):
        raise Exception('needs to be updated')
    annotation_list = []
    for sfo in seqlist:
        uid = sfo['name']
        trid = get_trid(uid, sfo['seq'])
        if trid not in returnfo['annotations']:
            assert trid in returnfo['failures']
            line = {'invalid' : True}
        else:
            line = returnfo['annotations'][trid]  # these aren't really annotations, they just have a few random keys. I should've called them something else
        assert 'unique_ids' not in line  # make sure it wasn't added, since if it was we'd need to change it
        line['unique_ids'] = [uid]
        annotation_list.append(line)
    return annotation_list  # eh, probably don't need this:, returnfo['gene-counts']  # NOTE both annotation_list and <failures> can have duplicate uids in them

# ----------------------------------------------------------------------------------------
# NOTE use the previous fcn if you expect duplicate uids
def run_vsearch(action, seqdict, workdir, threshold, match_mismatch='2:-4', no_indels=False, minseqlength=None, consensus_fname=None, msa_fname=None, glfo=None, print_time=False, vsearch_binary=None, get_annotations=False, expect_failure=False, extra_str='  vsearch:'):
    # note: '2:-4' is the default vsearch match:mismatch, but I'm setting it here in case vsearch changes it in the future
    # single-pass, greedy, star-clustering algorithm with
    #  - add the target to the cluster if the pairwise identity with the centroid is higher than global threshold <--id>
    #  - pairwise identity definition <--iddef> defaults to: number of (matching columns) / (alignment length - terminal gaps)
    #  - the search process sorts sequences in decreasing order of number of k-mers in common
    #    - the search process stops after --maxaccept matches (default 1), and gives up after --maxreject non-matches (default 32)
    #    - If both are zero, it searches the whole database
    #    - I do not remember why I set both to zero. I just did a quick test, and on a few thousand sequences, it seems to be somewhat faster with the defaults, and a tiny bit less accurate.
    region = 'v'
    userfields = [  # all 1-indexed (note: only used for 'search')
        'query',
        'target',
        'qilo',  # first pos of query that aligns to target (1-indexed), skipping initial gaps (e.g. 1 if first pos aligns, 4 if fourth pos aligns but first three don't)
        'qihi',  # last pos of same (1-indexed)
        'tilo',  # same, but pos of target that aligns to query (1-indexed)
        'tihi',  # last pos of same (1-indexed)
        'ids',
        'caln',  # cigar string
    ]
    expected_success_fraction = 0.75  # if we get alignments for fewer than this, print a warning cause something's probably wrong

    start = time.time()
    prep_dir(workdir)
    infname = workdir + '/input.fa'

    # write input
    with open(infname, 'w') as fastafile:
        for name, seq in seqdict.items():
            fastafile.write('>' + name + '\n' + seq + '\n')

    # figure out which vsearch binary to use
    if vsearch_binary is None:
        vsearch_binary = os.path.dirname(os.path.realpath(__file__)).replace('/python', '') + '/bin'
        if platform.system() == 'Linux':
            vsearch_binary += '/vsearch-2.4.3-linux-x86_64'
        elif platform.system() == 'Darwin':
            vsearch_binary += '/vsearch-2.4.3-macos-x86_64'
        else:
            raise Exception('%s no vsearch binary in bin/ for platform \'%s\' (you can specify your own full vsearch path with --vsearch-binary)' % (color('red', 'error'), platform.system()))

    # build command
    cmd = vsearch_binary
    cmd += ' --id ' + str(1. - threshold)  # reject if identity lower than this
    match, mismatch = [int(m) for m in match_mismatch.split(':')]
    assert mismatch < 0  # if you give it a positive one it doesn't complain, so presumably it's actually using that positive  (at least for v identification it only makes a small difference, but vsearch's default is negative)
    cmd += ' --match %d'  % match  # default 2
    cmd += ' --mismatch %d' % mismatch  # default -4
    # cmd += ' --gapext %dI/%dE' % (2, 1)  # default: (2 internal)/(1 terminal)
    # it would be nice to clean this up
    gap_open = 1000 if no_indels else 50
    cmd += ' --gapopen %dI/%dE' % (gap_open, 2)  # default: (20 internal)/(2 terminal)
    if minseqlength is not None:
        cmd += ' --minseqlength %d' % minseqlength
    if action == 'cluster':
        outfname = workdir + '/vsearch-clusters.txt'
        cmd += ' --cluster_fast ' + infname
        cmd += ' --uc ' + outfname
        if consensus_fname is not None:  # workdir cleanup below will fail if you put it in this workdir
            cmd += ' --consout ' + consensus_fname  # note: can also output a file with msa and consensus
        if msa_fname is not None:  # workdir cleanup below will fail if you put it in this workdir
            cmd += ' --msaout ' + msa_fname
        # cmd += ' --maxaccept 0 --maxreject 0'  # see note above
    elif action == 'search':
        outfname = workdir + '/aln-info.tsv'
        dbdir = workdir + '/' + glutils.glfo_dir
        glutils.write_glfo(dbdir, glfo)
        cmd += ' --usearch_global ' + infname
        cmd += ' --maxaccepts 5'  # it's sorted by number of k-mers in common, so this needs to be large enough that we'll almost definitely get the exact best gene match
        cmd += ' --db ' + glutils.get_fname(dbdir, glfo['locus'], region)
        cmd += ' --userfields %s --userout %s' % ('+'.join(userfields), outfname)  # note that --sizeout --dbmatched <fname> adds up all the matches from --maxaccepts, i.e. it's not what we want
    else:
        assert False
    # cmd += ' --threads ' + str(n_procs)  # a.t.m. just let vsearch use all the cores (it'd be nice to be able to control it a little, but it's hard to keep it separate from the number of slurm procs, and we pretty much always want it to be different to that)
    cmd += ' --quiet'
    cmdfos = [{
        'cmd_str' : cmd,
        'outfname' : outfname,
        'workdir' : workdir,
        # 'threads' : n_procs},  # NOTE that this does something very different (adjusts slurm command) to the line above ^ (which talks to vsearch)
    }]

    # run
    run_cmds(cmdfos)

    # read output
    if action == 'cluster':
        returnfo = read_vsearch_cluster_file(outfname)
    elif action == 'search':
        returnfo = read_vsearch_search_file(outfname, userfields, seqdict, glfo, region, get_annotations=get_annotations)
        glutils.remove_glfo_files(dbdir, glfo['locus'])
        succ_frac = sum(returnfo['gene-counts'].values()) / float(len(seqdict))
        if succ_frac < expected_success_fraction and not expect_failure:
            print '%s vsearch only managed to align %d / %d = %.3f of the input sequences (cmd below)   %s\n  %s' % (color('yellow', 'warning'), sum(returnfo['gene-counts'].values()), len(seqdict), sum(returnfo['gene-counts'].values()) / float(len(seqdict)), reverse_complement_warning(), cmd)
    else:
        assert False
    os.remove(infname)
    os.remove(outfname)
    os.rmdir(workdir)

    if print_time:
        if action == 'search':
            # NOTE you don't want to remove these failures, since sw is much smarter about alignment than vsearch, i.e. some failures here are actually ok
            n_passed = int(round(sum(returnfo['gene-counts'].values())))
            tw = str(len(str(len(seqdict))))  # width of format str from number of digits in N seqs
            print ('%s %'+tw+'d / %-'+tw+'d %s annotations (%d failed) with %d %s gene%s in %.1f sec') % (extra_str, n_passed, len(seqdict), region, len(seqdict) - n_passed, len(returnfo['gene-counts']),
                                                                                                          region, plural(len(returnfo['gene-counts'])), time.time() - start)
        else:
            print 'can\'t yet print time for clustering'

    return returnfo

# ----------------------------------------------------------------------------------------
def run_swarm(seqs, workdir, differences=1, n_procs=1):
    # groups together all sequence pairs that have <d> or fewer differences (--differences, default 1)
    #  - if d=1, uses algorithm of linear complexity (d=2 or greater uses quadratic algorithm)
    #  - --fastidious (only for d=1) extra pass to reduce the number of small OTUs

    prep_dir(workdir)
    infname = workdir + '/input.fa'
    outfname = workdir + '/clusters.txt'

    dummy_abundance = 1
    with open(infname, 'w') as fastafile:
        for name, seq in seqs.items():
            fastafile.write('>%s_%d\n%s\n' % (name, dummy_abundance, remove_ambiguous_ends(seq).replace('N', 'A')))

    cmd = os.path.dirname(os.path.realpath(__file__)).replace('/python', '') + '/bin/swarm-2.1.13-linux-x86_64 ' + infname
    cmd += ' --differences ' + str(differences)
    if differences == 1:
        cmd += ' --fastidious'
    cmd += ' --threads ' + str(n_procs)
    cmd += ' --output-file ' + outfname
    simplerun(cmd)

    partition = []
    with open(outfname) as outfile:
        for line in outfile:
            partition.append([uidstr.rstrip('_%s' % dummy_abundance) for uidstr in line.strip().split()])

    os.remove(infname)
    os.remove(outfname)
    os.rmdir(workdir)

    cp = clusterpath.ClusterPath()
    cp.add_partition(partition, logprob=0., n_procs=1)
    cp.print_partitions(abbreviate=True)

    return partition


# ----------------------------------------------------------------------------------------
def compare_vsearch_to_sw(sw_info, vs_info):
    # pad vsearch indel info so it'll match the sw indel info (if the sw indel info is just copied from the vsearch info, and you're not going to use the vsearch info for anything after, there's no reason to do this)
    for query in sw_info['indels']:
        if query not in sw_info['queries']:
            continue
        if query not in vs_info['annotations']:
            continue
        if not indelutils.has_indels(vs_info['annotations'][query]['indelfo']):
            continue
        indelutils.pad_indelfo(vs_info['annotations'][query]['indelfo'], ambig_base * sw_info[query]['padlefts'][0], ambig_base * sw_info[query]['padrights'][0])

    from hist import Hist
    hists = {
        # 'mfreq' : Hist(30, -0.1, 0.1),
        # 'n_muted' : Hist(20, -10, 10),
        # 'vs' : Hist(30, 0., 0.4),
        # 'sw' : Hist(30, 0., 0.4),
        'n_indels' : Hist(7, -3.5, 3.5),
        'pos' : Hist(21, -10.5, 10.5),
        'len' : Hist(11, -5, 5),
        # 'type' : Hist(2, -0.5, 1.5),
    }

    for uid in sw_info['queries']:
        if uid not in vs_info['annotations']:
            continue
        vsfo = vs_info['annotations'][uid]
        swfo = sw_info[uid]
        # swmfreq, swmutations = utils.get_mutation_rate_and_n_muted(swfo, iseq=0, restrict_to_region='v')
        # hists['mfreq'].fill(vsfo['v_mut_freq'] - swmfreq)
        # hists['n_muted'].fill(vsfo['n_v_mutations'] - swmutations)
        # hists['vs'].fill(vsfo['v_mut_freq'])
        # hists['sw'].fill(swmfreq)
        iindel = 0
        vsindels = vsfo['indelfo']['indels']
        swindels = swfo['indelfos'][0]['indels']
        hists['n_indels'].fill(len(vsindels) - len(swindels))
        if len(vsindels) == 0 or len(swindels) == 0:
            continue
        vsindels = sorted(vsindels, key=lambda d: (d['len'], d['pos']), reverse=True)
        swindels = sorted(swindels, key=lambda d: (d['len'], d['pos']), reverse=True)
        for name in [n for n in hists if n != 'n_indels']:
            hists[name].fill(vsindels[iindel][name] - swindels[iindel][name])

    import plotting
    for name, hist in hists.items():
        fig, ax = plotting.mpl_init()
        hist.mpl_plot(ax, hist, label=name, color=plotting.default_colors[hists.keys().index(name)])
        # hist.write('_output/vsearch-test/%s/%s.csv' % (match_mismatch.replace(':', '-'), name))
        plotting.mpl_finish(ax, '.', name, xlabel='vs - sw')

# ----------------------------------------------------------------------------------------
def get_chimera_max_abs_diff(line, iseq, chunk_len=75, max_ambig_frac=0.1, debug=False):
    naive_seq, mature_seq = subset_iseq(line, iseq, restrict_to_region='v')  # self.info[uid]['naive_seq'], self.info[uid]['seqs'][0]

    if ambig_frac(naive_seq) > max_ambig_frac or ambig_frac(mature_seq) > max_ambig_frac:
        if debug:
            print '  too much ambig %.2f %.2f' % (ambig_frac(naive_seq), ambig_frac(mature_seq))
        return None, 0.

    if debug:
        color_mutants(naive_seq, mature_seq, print_result=True)
        print ' '.join(['%3d' % s for s in isnps])

    _, isnps = hamming_distance(naive_seq, mature_seq, return_mutated_positions=True)

    max_abs_diff, imax = 0., None
    for ipos in range(chunk_len, len(mature_seq) - chunk_len):
        if debug:
            print ipos

        muts_before = [isn for isn in isnps if isn >= ipos - chunk_len and isn < ipos]
        muts_after = [isn for isn in isnps if isn >= ipos and isn < ipos + chunk_len]
        mfreq_before = len(muts_before) / float(chunk_len)
        mfreq_after = len(muts_after) / float(chunk_len)

        if debug:
            print '    len(%s) / %d = %.3f' % (muts_before, chunk_len, mfreq_before)
            print '    len(%s) / %d = %.3f' % (muts_after, chunk_len, mfreq_after)

        abs_diff = abs(mfreq_before - mfreq_after)
        if imax is None or abs_diff > max_abs_diff:
            max_abs_diff = abs_diff
            imax = ipos

    return imax, max_abs_diff  # <imax> is break point

# ----------------------------------------------------------------------------------------
def get_version_info(debug=False):
    git_dir = os.path.dirname(os.path.realpath(__file__)).replace('/python', '/.git')
    vinfo = {}
    vinfo['commit'] = subprocess.check_output(['git', '--git-dir', git_dir, 'rev-parse', 'HEAD']).strip()
    if debug:
        print '  commit: %s' % vinfo['commit']
    cmd = 'git --git-dir %s describe --always --tags' % git_dir
    out, err = simplerun(cmd, return_out_err=True, debug=False)
    if '-' in out:
        if out.count('-') == 2:
            vinfo['tag'], vinfo['n_ahead_of_tag'], commit_hash_abbrev = out.strip().split('-')
            if debug:
                ahead_str = ''
                if int(vinfo['n_ahead_of_tag']) > 0:
                    ahead_str = '  (well, %d commits ahead of)' % int(vinfo['n_ahead_of_tag'])
                print '     tag: %s%s' % (vinfo['tag'], ahead_str)
        else:
            vinfo['tag'] = '?'
            print '    %s utils.get_version_info() couldn\'t figure out tag from \'%s\' output: %s' % (color('red', 'error'), cmd, out)
    else:
        vinfo['tag'] = out.strip()
        print '     tag: %s' % vinfo['tag']

    return vinfo

# ----------------------------------------------------------------------------------------
def write_annotations(fname, glfo, annotation_list, headers, synth_single_seqs=False, failed_queries=None, partition_lines=None, use_pyyaml=False, dont_write_git_info=False):
    if os.path.exists(fname):
        os.remove(fname)
    elif not os.path.exists(os.path.dirname(os.path.abspath(fname))):
        os.makedirs(os.path.dirname(os.path.abspath(fname)))

    if getsuffix(fname) == '.csv':
        assert partition_lines is None
        write_csv_annotations(fname, headers, annotation_list, synth_single_seqs=synth_single_seqs, glfo=glfo, failed_queries=failed_queries)
    elif getsuffix(fname) == '.yaml':
        if partition_lines is None:
            partition_lines = clusterpath.ClusterPath(partition=get_partition_from_annotation_list(annotation_list)).get_partition_lines(True)  # setting is_data to True here since we can't pass in reco_info and whatnot anyway
        write_yaml_output(fname, headers, glfo=glfo, annotation_list=annotation_list, synth_single_seqs=synth_single_seqs, failed_queries=failed_queries, partition_lines=partition_lines, use_pyyaml=use_pyyaml, dont_write_git_info=dont_write_git_info)
    else:
        raise Exception('unhandled file extension %s' % getsuffix(fname))

# ----------------------------------------------------------------------------------------
def write_csv_annotations(fname, headers, annotation_list, synth_single_seqs=False, glfo=None, failed_queries=None):
    with open(fname, 'w') as csvfile:
        writer = csv.DictWriter(csvfile, headers)
        writer.writeheader()
        for line in annotation_list:
            if synth_single_seqs:
                for iseq in range(len(line['unique_ids'])):
                    outline = get_line_for_output(headers, synthesize_single_seq_line(line, iseq), glfo=glfo)
                    writer.writerow(outline)
            else:
                outline = get_line_for_output(headers, line, glfo=glfo)
                writer.writerow(outline)
        if failed_queries is not None:
            for failfo in failed_queries:
                assert len(failfo['unique_ids']) == 1
                writer.writerow({'unique_ids' : failfo['unique_ids'][0], 'invalid' : failfo['invalid'], 'input_seqs' : failfo['input_seqs'][0]})  # this is ugly, but the corresponding one in the yaml fcn is nice

# ----------------------------------------------------------------------------------------
def get_yamlfo_for_output(line, headers, glfo=None):
    yamlfo = {}
    transfer_indel_info(line, yamlfo)
    for key in [k for k in headers if k not in yamlfo]:
        if key in line:
            yamlfo[key] = line[key]
        elif key in input_metafile_keys.values():  # these are optional, so if they're missing, don't worry about it
            continue
        else:
            if line['invalid']:
                continue
            add_extra_column(key, line, yamlfo, glfo=glfo)
    return yamlfo

# ----------------------------------------------------------------------------------------
def write_yaml_output(fname, headers, glfo=None, annotation_list=None, synth_single_seqs=False, failed_queries=None, partition_lines=None, use_pyyaml=False, dont_write_git_info=False):
    if annotation_list is None:
        annotation_list = []
    if partition_lines is None:
        partition_lines = []

    version_info = {'partis-yaml' : 0.1, 'partis-git' : '' if dont_write_git_info else get_version_info()}
    yaml_annotations = [get_yamlfo_for_output(l, headers, glfo=glfo) for l in annotation_list]
    if failed_queries is not None:
        yaml_annotations += failed_queries
    yamldata = {'version-info' : version_info,
                'germline-info' : glfo,
                'partitions' : partition_lines,
                'events' : yaml_annotations}
    with open(fname, 'w') as yamlfile:
        if use_pyyaml:  # slower, but easier to read by hand for debugging (use this instead of the json version to make more human-readable files)
            yaml.dump(yamldata, yamlfile, width=400, Dumper=yaml.CDumper, default_flow_style=False, allow_unicode=False)  # set <allow_unicode> to false so the file isn't cluttered up with !!python.unicode stuff
        else:  # way tf faster than full yaml (only lost information is ordering in ordered dicts, but that's only per-gene support and germline info, neither of whose order we care much about)
            json.dump(yamldata, yamlfile) #, sort_keys=True, indent=4)

# ----------------------------------------------------------------------------------------
def parse_yaml_annotations(glfo, yamlfo, n_max_queries, synth_single_seqs, dont_add_implicit_info):
    annotation_list = []
    n_queries_read = 0
    for line in yamlfo['events']:
        if not line['invalid']:
            transfer_indel_reversed_seqs(line)
            if 'all_matches' in line and isinstance(line['all_matches'], dict):  # it used to be per-family, but then I realized it should be per-sequence, so any old cache files lying around have it as per-family
                line['all_matches'] = [line['all_matches']]  # also, yes, it makes me VERY ANGRY that this needs to be here, but i just ran into a couple of these old files and otherwise they cause crashes
            if not dont_add_implicit_info:  # it's kind of slow, although most of the time you probably want all the extra info
                add_implicit_info(glfo, line)  # don't use the germline info in <yamlfo>, in case we decide we want to modify it in the calling fcn
        if synth_single_seqs and len(line['unique_ids']) > 1:
            for iseq in range(len(line['unique_ids'])):
                annotation_list.append(synthesize_single_seq_line(line, iseq))
        else:
            annotation_list.append(line)

        n_queries_read += len(line['unique_ids'])
        if n_max_queries > 0 and n_queries_read >= n_max_queries:
            break

    return annotation_list

# ----------------------------------------------------------------------------------------
def read_output(fname, n_max_queries=-1, synth_single_seqs=False, dont_add_implicit_info=False, seed_unique_id=None, cpath=None, skip_annotations=False, glfo=None, glfo_dir=None, locus=None, debug=False):
    annotation_list = None

    if getsuffix(fname) == '.csv':
        cluster_annotation_fname = fname.replace('.csv', '-cluster-annotations.csv')
        if os.path.exists(cluster_annotation_fname):  # i.e. if <fname> is a partition file
            assert cpath is None   # see note in read_yaml_output()
            cpath = clusterpath.ClusterPath(fname=fname, seed_unique_id=seed_unique_id)  # NOTE I'm not sure if I really want to pass in the seed here -- it should be stored in the file -- but if it's in both places it should be the same. um, should.
            fname = cluster_annotation_fname  # kind of hackey, but oh well

        if not skip_annotations:
            if not dont_add_implicit_info and glfo is None:
                if glfo_dir is not None:
                    glfo = glutils.read_glfo(glfo_dir, locus)
                else:
                    raise Exception('glfo is None, but we were asked to add implicit info for an (old-style) csv output file')
            n_queries_read = 0
            annotation_list = []
            with open(fname) as csvfile:
                for line in csv.DictReader(csvfile):
                    process_input_line(line, skip_literal_eval=dont_add_implicit_info)  # NOTE kind of weird to equate implicit info adding and literal eval skipping... but in the end they're both mostly speed optimizations
                    if not dont_add_implicit_info:
                        add_implicit_info(glfo, line)
                    annotation_list.append(line)
                    n_queries_read += 1
                    if n_max_queries > 0 and n_queries_read >= n_max_queries:
                        break

    elif getsuffix(fname) == '.yaml':  # NOTE this replaces any <glfo> that was passed (well, only within the local name table of this fcn, unless the calling fcn replaces it themselves, since we return this glfo)
        glfo, annotation_list, cpath = read_yaml_output(fname, n_max_queries=n_max_queries, synth_single_seqs=synth_single_seqs,
                                                        dont_add_implicit_info=dont_add_implicit_info, seed_unique_id=seed_unique_id, cpath=cpath, skip_annotations=skip_annotations, debug=debug)
    else:
        raise Exception('unhandled file extension %s' % getsuffix(fname))

    if len(cpath.partitions) == 0 and not skip_annotations:  # old simulation files didn't write the partition separately, but we may as well get it
        cpath.add_partition(get_partition_from_annotation_list(annotation_list), -1., 1)

    return glfo, annotation_list, cpath  # NOTE if you want a dict of annotations, use utils.get_annotation_dict() above

# ----------------------------------------------------------------------------------------
def read_yaml_output(fname, n_max_queries=-1, synth_single_seqs=False, dont_add_implicit_info=False, seed_unique_id=None, cpath=None, skip_annotations=False, debug=False):
    with open(fname) as yamlfile:
        try:
            yamlfo = json.load(yamlfile)  # way tf faster than full yaml (only lost information is ordering in ordered dicts, but that's only per-gene support and germline info, neither of whose order we care much about)
        except ValueError:  # I wish i could think of a better way to do this, but I can't
            yamlfile.seek(0)
            yamlfo = yaml.load(yamlfile, Loader=yaml.CLoader)  # use this instead of the json version to make more human-readable files
        if debug:
            print '  read yaml version %s from %s' % (yamlfo['version-info']['partis-yaml'], fname)

    glfo = yamlfo['germline-info']  # it would probably be good to run the glfo through the checks that glutils.read_glfo() does, but on the other hand since we're reading from our own yaml file, those have almost certainly already been done

    annotation_list = None
    if not skip_annotations:  # may not really be worthwhile, but oh well
        annotation_list = parse_yaml_annotations(glfo, yamlfo, n_max_queries, synth_single_seqs, dont_add_implicit_info)

    partition_lines = yamlfo['partitions']
    if cpath is None:   # allowing the caller to pass in <cpath> is kind of awkward, but it's used for backward compatibility in clusterpath.readfile()
        cpath = clusterpath.ClusterPath(seed_unique_id=seed_unique_id)  # NOTE I'm not sure if I really want to pass in the seed here -- it should be stored in the file -- but if it's in both places it should be the same. um, should.
    if len(partition_lines) > 0:  # *don't* combine this with the cluster path constructor, since then we won't modify the path passed in the arguments
        cpath.readlines(partition_lines)

    return glfo, annotation_list, cpath  # NOTE if you want a dict of annotations, use utils.get_annotation_dict() above

# ----------------------------------------------------------------------------------------
def get_gene_counts_from_annotations(annotations, only_regions=None):
    gene_counts = {r : {} for r in (only_regions if only_regions is not None else regions)}
    for query, line in annotations.items():
        for tmpreg in gene_counts:
            gene = line[tmpreg + '_gene']
            if gene not in gene_counts[tmpreg]:
                gene_counts[tmpreg][gene] = 0.
            gene_counts[tmpreg][gene] += 1.  # vsearch info counts partial matches based of score, but I don't feel like dealing with that here at the moment
    return gene_counts
