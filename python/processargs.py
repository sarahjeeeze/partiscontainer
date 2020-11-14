import os
import random
import sys
import subprocess

import utils
import glutils

def get_dummy_outfname(workdir, light_chain=False):
    return '%s/XXX-dummy-simu%s.yaml' % (workdir, '-light' if light_chain else '')

parameter_type_choices = ('sw', 'hmm', 'multi-hmm')

# ----------------------------------------------------------------------------------------
# split this out so we can call it from both bin/partis and bin/test-germline-inference.py
def process_gls_gen_args(args):  # well, also does stuff with non-gls-gen new allele args
    if args.locus is not None:  # if --paired-loci is not set
        if args.n_genes_per_region is None:
            args.n_genes_per_region = glutils.default_n_genes_per_region[args.locus]
        if args.n_sim_alleles_per_gene is None:
            args.n_sim_alleles_per_gene = glutils.default_n_alleles_per_gene[args.locus]
    positions = {
        'snp' : utils.get_arg_list(args.snp_positions),
        'indel' : utils.get_arg_list(args.indel_positions),
    }
    numbers = {
        'snp' : utils.get_arg_list(args.nsnp_list, intify=True),
        'indel' : utils.get_arg_list(args.nindel_list, intify=True),
    }
    delattr(args, 'snp_positions')  # just to make sure you don't accidentally use them (should only use the new args.new_allele_info that gets created below)
    delattr(args, 'indel_positions')
    delattr(args, 'nsnp_list')
    delattr(args, 'nindel_list')

    n_new_alleles = None
    mtypes = ['snp', 'indel']
    for mtype in mtypes:
        if positions[mtype] is not None:  # if specific positions were specified on the command line
            positions[mtype] = [[int(p) for p in pos_str.split(',')] for pos_str in positions[mtype]]  # NOTE I think I could switch this to utils.get_arg_list() with list_of_lists=True
            if len(positions[mtype]) != len(args.sim_v_genes):  # we shouldn't be able to get here unless args has .sim_v_genes
                raise Exception('--%s-positions %s and --sim-v-genes %s not the same length (%d vs %d)' % (mtype, positions[mtype], args.sim_v_genes, len(positions[mtype]), len(args.sim_v_genes)))
        if numbers[mtype] is not None:
            if not args.generate_germline_set and len(numbers[mtype]) != len(args.sim_v_genes):  # we shouldn't be able to get here unless args has .sim_v_genes
                raise Exception('--n%s-list %s and --sim-v-genes %s not the same length (%d vs %d)' % (mtype, numbers[mtype], args.sim_v_genes, len(numbers[mtype]), len(args.sim_v_genes)))
            if positions[mtype] is not None:
                raise Exception('can\'t specify both --n%s-list and --%s-positions' % (mtype, mtype))
            positions[mtype] = [[None for _ in range(number)] for number in numbers[mtype]]  # the <None> tells glutils to choose a position at random
        if positions[mtype] is not None:
            if n_new_alleles is None:
                n_new_alleles = len(positions[mtype])
            if len(positions[mtype]) != n_new_alleles:
                raise Exception('mismatched number of new alleles for %s' % ' vs '.join(mtypes))
    if n_new_alleles is None:
        n_new_alleles = 0
    for mtype in mtypes:
        if positions[mtype] is None:  # if it wasn't specified at all, i.e. we don't want to generate any new alleles
            positions[mtype] = [[] for _ in range(n_new_alleles)]
    args.new_allele_info = [{'gene' : args.sim_v_genes[igene] if not args.generate_germline_set else None,  # we shouldn't be able to get here unless args has .sim_v_genes
                             'snp-positions' : positions['snp'][igene],
                             'indel-positions' : positions['indel'][igene]}
                            for igene in range(n_new_alleles)]

# ----------------------------------------------------------------------------------------
def get_workdir(batch_system):  # split this out so we can use it in datascripts (ok, then I ended up commenting it in datascripts, but maybe later I want to uncomment)
    basestr = os.getenv('USER', default='partis-work')
    if batch_system is not None and os.path.exists('/fh/fast/matsen_e'):
        workdir = utils.choose_random_subdir('/fh/fast/matsen_e/%s/_tmp/hmms' % basestr)
    else:
        workdir = utils.choose_random_subdir('/tmp/%s/hmms' % basestr)
        if batch_system is not None:
            print '  %s: using batch system %s with default --workdir (%s) -- if this dir isn\'t visible to your batch nodes, you\'ll need to set --workdir to something that is' % (utils.color('red', 'warning'), batch_system, workdir)
    return workdir

# ----------------------------------------------------------------------------------------
def process(args):
    if args.action == 'run-viterbi':
        print'  note: replacing deprecated action name \'run-viterbi\' with current name \'annotate\' (you don\'t need to change anything unless you want this warning message to go away)'
        args.action = 'annotate'
    if args.action == 'get-tree-metrics':
        print'  note: replacing deprecated action name \'get-tree-metrics\' with current name \'get-selection-metrics\' (you don\'t need to change anything unless you want this warning message to go away)'
        args.action = 'get-selection-metrics'
    if args.get_tree_metrics:
        print '    note: replacing deprecated option \'--get-tree-metrics\' with new option \'--get-selection-metrics\' (you don\'t need to change anything unless you want this warning message to go away)'
        args.get_selection_metrics = True
        delattr(args, 'get_tree_metrics')
    if args.action == 'view-alternative-naive-seqs':
        print'  note: replacing deprecated action name \'view-alternative-naive-seqs\' with current name \'view-alternative-annotations\' (you don\'t need to change anything unless you want this warning message to go away)'
        args.action = 'view-alternative-annotations'
    if args.calculate_alternative_naive_seqs:
        print '    note: replacing deprecated option \'--calculate-alternative-naive-seqs\' with new option \'--calculate-alternative-annotations\' (you don\'t need to change anything unless you want this warning message to go away)'
        args.calculate_alternative_annotations = True
        delattr(args, 'calculate_alternative_naive_seqs')

    args.paired_loci = utils.get_arg_list(args.paired_loci, choices=utils.loci)
    if args.paired_loci is not None:
        if len(args.paired_loci) != 2:
            raise Exception('--paired-loci must be length two: can only do either igh:igk or igh:igl, not arbitrary mixtures of k and l')
        args.locus = None
        for argstr in ['infname', 'outfname', 'parameter-dir']:
            argvals = [getattr(args, (lstr+argstr).replace('-', '_')) for lstr in ['', 'light-chain-']]
            if argvals.count(None) == 1:
                raise Exception('--paired-loci is set, so either both or neither of --%s and --light-chain-%s must be set (exactly one was set)' % (argstr, argstr))
    if args.action == 'merge-paired-partitions':
        assert args.paired_loci is not None or args.split_loci
    if args.split_loci:
        assert args.paired_loci is None
        if [args.light_chain_infname, args.light_chain_outfname, args.light_chain_parameter_dir] != [None, None, None]:
            raise Exception('none of the --light-chain-<stuff> arguments should be set when --split-loci is set')  # they get set in the subprocesses we start
        if args.paired_loci_output_dir is None:
            raise Exception('have to set --paired-loci-output-dir if --split-loci is set')
        if args.outfname is not None:
            raise Exception('can\'t set --outfname if --split-loci is set (use --paired-loci-output-dir)')
    if args.reverse_negative_strands and not args.split_loci:
        raise Exception('--reverse-negative-strands has no effect unless --split-loci is set (maybe need to run bin/split-loci.py separately?)')

    args.only_genes = utils.get_arg_list(args.only_genes)
    args.queries = utils.get_arg_list(args.queries)
    args.queries_to_include = utils.get_arg_list(args.queries_to_include)
    args.reco_ids = utils.get_arg_list(args.reco_ids)
    args.istartstop = utils.get_arg_list(args.istartstop, intify=True)
    if args.istartstop is not None:
        if args.istartstop[0] >= args.istartstop[1] or args.istartstop[0] < 0:
            raise Exception('invalid --istartstop specification: %d %d' % (args.istartstop[0], args.istartstop[1]))
    args.n_max_per_region = utils.get_arg_list(args.n_max_per_region, intify=True)
    if len(args.n_max_per_region) != 3:
        raise Exception('n-max-per-region should be of the form \'x:y:z\', but I got ' + str(args.n_max_per_region))
    args.write_additional_cluster_annotations = utils.get_arg_list(args.write_additional_cluster_annotations, intify=True)
    if args.write_additional_cluster_annotations is not None and len(args.write_additional_cluster_annotations) != 2:
        raise Exception('--write-additional-cluster-annotations must be specified as two numbers \'m:n\', but I got %s' % args.write_additional_cluster_annotations)
    args.extra_annotation_columns = utils.get_arg_list(args.extra_annotation_columns, choices=utils.extra_annotation_headers)

    args.cluster_indices = utils.get_arg_list(args.cluster_indices, intify_with_ranges=True)

    args.allowed_cdr3_lengths = utils.get_arg_list(args.allowed_cdr3_lengths, intify=True)

    args.region_end_exclusions = {r : [args.region_end_exclusion_length if ('%s_%s' % (r, e)) in utils.real_erosions else 0 for e in ['5p', '3p']] for r in utils.regions}
    args.region_end_exclusion_length = None  # there isn't really a big reason to set it to None, but this makes clear that I should only be using the dict version

    args.typical_genes_per_region_per_subject = utils.get_arg_list(args.typical_genes_per_region_per_subject, intify=True)
    if len(args.typical_genes_per_region_per_subject) != len(utils.regions):
        raise Exception('wrong length for --typical-genes-per-region-per-subject, has to be three')
    tmpfrac, ntmp = args.min_allele_prevalence_fraction, args.typical_genes_per_region_per_subject
    args.min_allele_prevalence_fractions = {r : tmpfrac * ntmp[utils.regions.index('v')] / ntmp[utils.regions.index(r)] for r in utils.regions}
    delattr(args, 'min_allele_prevalence_fraction')  # delete the non-plural version
    delattr(args, 'typical_genes_per_region_per_subject')  # and we don't need this any more either

    args.annotation_clustering_thresholds = utils.get_arg_list(args.annotation_clustering_thresholds, floatify=True)
    args.naive_hamming_bounds = utils.get_arg_list(args.naive_hamming_bounds, floatify=True)
    if args.small_clusters_to_ignore is not None:
        if '-' in args.small_clusters_to_ignore:
            lo, hi = [int(cluster_size) for cluster_size in args.small_clusters_to_ignore.split('-')]
            args.small_clusters_to_ignore = range(lo, hi + 1)
        else:
            args.small_clusters_to_ignore = utils.get_arg_list(args.small_clusters_to_ignore, intify=True)
    if args.seed_unique_id is not None:
        args.seed_unique_id = args.seed_unique_id.strip()  # protect against the space you may put in front of it if it's got an initial minus sign (better way is to use an equals sign)
        if args.queries is not None and args.seed_unique_id not in args.queries:
            raise Exception('seed uid %s not in --queries %s' % (args.seed_unique_id, ' '.join(args.queries)))
        if args.random_seed_seq:
            raise Exception('can\'t specify both --seed-unique-id and --random-seed-seq')

        if args.queries_to_include is None:  # make sure the seed is in --queries-to-include
            args.queries_to_include = [args.seed_unique_id]
        elif args.seed_unique_id not in args.queries_to_include:
            args.queries_to_include = [args.seed_unique_id] + args.queries_to_include  # may as well put it first, I guess (?)
    elif args.seed_seq is not None:
        args.seed_unique_id = 'seed-seq'

    if args.sw_debug is None:  # if not explicitly set, set equal to regular debug
        args.sw_debug = args.debug

    if args.only_genes is not None:
        for gene in args.only_genes:  # make sure they're all at least valid ig genes
            utils.split_gene(gene)

    if args.print_git_commit or args.action == 'version':
        utils.get_version_info(debug=True)
        if args.action == 'version':
            sys.exit(0)

    args.is_data = not args.is_simu  # whole code base uses is_data, this is better than changing all of that

    if args.collapse_duplicate_sequences and not args.is_data:
        print '  %s collapsing duplicates on simulation, which is often not a good idea since it makes keeping track of performance harder (e.g. purity/completeness of partitions is harder to calculate)' % utils.color('red', 'warning')

    if args.simultaneous_true_clonal_seqs:
        if args.is_data:
            raise Exception('can only pass true clonal families to multi-hmm together on simulation and with --is-simu set')
        if args.n_simultaneous_seqs is not None:
            raise Exception('can\'t specify both --n-simultaneous-seqs and --simultaneous-true-clonal-seqs')
        if args.all_seqs_simultaneous:
            raise Exception('can\'t specify both --all-seqs-simultaneous and --simultaneous-true-clonal-seqs')
    if args.n_simultaneous_seqs is not None and args.all_seqs_simultaneous:
        raise Exception('doesn\'t make sense to set both --n-simultaneous-seqs and --all-seqs-simultaneous.')

    if args.no_indels:
        print 'forcing --gap-open-penalty to %d to prevent indels, since --no-indels was specified (you can also adjust this penalty directly)' % args.no_indel_gap_open_penalty
        args.gap_open_penalty = args.no_indel_gap_open_penalty

    if args.indel_frequency > 0.:
        if args.indel_frequency < 0. or args.indel_frequency > 1.:
            raise Exception('--indel-frequency must be in [0., 1.] (got %f)' % args.indel_frequency)
    args.n_indels_per_indeld_seq = utils.get_arg_list(args.n_indels_per_indeld_seq, intify=True)
    if args.indel_location not in [None, 'v', 'cdr3']:
        if int(args.indel_location) in range(500):
            args.indel_location = int(args.indel_location)
            if any(n > 1 for n in args.n_indels_per_indeld_seq):
                print '  note: removing entries from --n-indels-per-indeld-seq (%s), since --indel-location was set to a single position.' % [n for n in args.n_indels_per_indeld_seq if n > 1]
                args.n_indels_per_indeld_seq = [n for n in args.n_indels_per_indeld_seq if n <= 1]
        else:
            raise Exception('--indel-location \'%s\' neither one of None, \'v\' or \'cdr3\', nor an integer less than 500' % args.indel_location)

    if args.locus is not None and 'tr' in args.locus and args.mutation_multiplier is None:
        args.mutation_multiplier = 0.

    if args.workdir is None:  # set default here so we know whether it was set by hand or not
        args.workdir = get_workdir(args.batch_system)
    else:
        args.workdir = args.workdir.rstrip('/')
    if os.path.exists(args.workdir):
        raise Exception('workdir %s already exists' % args.workdir)

    if args.paired_loci is not None:
        if args.outfname is None:  # need to write each locus's output to disk so we can merge their partition paths
            args.outfname = get_dummy_outfname(args.workdir)
            args.light_chain_outfname = get_dummy_outfname(args.workdir, light_chain=True)
    elif [args.light_chain_infname, args.light_chain_outfname, args.light_chain_parameter_dir] != [None, None, None]:
        raise Exception('doesn\'t make sense to set one of the --light-chain-<stuff> options unless --paired-loci is also set')

    if args.batch_system == 'sge' and args.batch_options is not None:
        if '-e' in args.batch_options or '-o' in args.batch_options:
            print '%s --batch-options contains \'-e\' or \'-o\', but we add these automatically since we need to be able to parse each job\'s stdout and stderr. You can control the directory under which they\'re written with --workdir (which is currently %s).' % (utils.color('red', 'warning'), args.workdir)

    if args.outfname is not None and not args.presto_output and not args.airr_output and not args.generate_trees:
        if utils.getsuffix(args.outfname) not in ['.csv', '.yaml']:
            raise Exception('unhandled --outfname suffix %s' % utils.getsuffix(args.outfname))
        if utils.getsuffix(args.outfname) != '.yaml':
            print '  %s --outfname uses deprecated file format %s. This will still mostly work ok, but the new default .yaml format doesn\'t have to do all the string conversions by hand (so is less buggy), and includes annotations, partitions, and germline info in the same file (so you don\'t get crashes or inconsistent results if you don\'t keep track of what germline info goes with what output file).' % (utils.color('yellow', 'note:'), utils.getsuffix(args.outfname))
        if args.action in ['view-annotations', 'view-partitions'] and utils.getsuffix(args.outfname) == '.yaml':
            raise Exception('have to use \'view-output\' action to view .yaml output files')

    if args.presto_output:
        if args.outfname is None:
            raise Exception('have to set --outfname if --presto-output is set')
        if args.action == 'annotate' and utils.getsuffix(args.outfname) != '.tsv':
            raise Exception('--outfname suffix has to be .tsv for annotation with --presto-output (got %s)' % utils.getsuffix(args.outfname))
        if args.action == 'partition' and utils.getsuffix(args.outfname) not in ['.fa', '.fasta']:
            raise Exception('--outfname suffix has to be .fa or .fasta for partitioning with --presto-output (got %s)' % utils.getsuffix(args.outfname))
        if args.aligned_germline_fname is None:
            assert args.locus is not None
            args.aligned_germline_fname = '%s/%s/imgt-alignments/%s.fa' % (args.default_initial_germline_dir, args.species, args.locus)
        if not os.path.exists(args.aligned_germline_fname):
            raise Exception('--aligned-germline-fname %s doesn\'t exist, but we need it in order to write presto output' % args.aligned_germline_fname)
    if args.airr_output:
        if args.outfname is None:
            raise Exception('have to set --outfname if --airr-output is set')
        if utils.getsuffix(args.outfname) == '.tsv':
            print '  note: writing only airr .tsv to %s' % args.outfname
        elif utils.getsuffix(args.outfname) in ['.yaml', '.csv']:
            print '  note: writing both partis %s to %s and airr .tsv to %s' % (utils.getsuffix(args.outfname), args.outfname, utils.replace_suffix(args.outfname, '.tsv'))
        else:
            raise Exception('--outfname suffix has to be either .tsv or .yaml if --airr-output is set (got %s)' % utils.getsuffix(args.outfname))
    if args.airr_input:
        args.seq_column = 'sequence'
        args.name_column = 'sequence_id'

    if args.cluster_annotation_fname is None and args.outfname is not None and utils.getsuffix(args.outfname) == '.csv':  # if it wasn't set on the command line (<outfname> _was_ set), _and_ if we were asked for a csv, then use the old file name format
        args.cluster_annotation_fname = utils.insert_before_suffix('-cluster-annotations', args.outfname)

    if args.calculate_alternative_annotations and args.outfname is None and args.paired_loci_output_dir is None:
        raise Exception('have to specify --outfname in order to calculate alternative annotations')
    if args.action == 'view-alternative-annotations' and args.persistent_cachefname is None:  # handle existing old-style output
        assert args.outfname is not None
        if os.path.exists(utils.getprefix(args.outfname) + '-hmm-cache.csv'):
            args.persistent_cachefname = utils.getprefix(args.outfname) + '-hmm-cache.csv'  # written by bcrham, so has to be csv, not yaml

    if args.action == 'get-selection-metrics' or args.get_selection_metrics:
        if args.outfname is None and args.selection_metric_fname is None:
                print '    %s calculating selection metrics, but neither --outfname nor --selection-metric-fname were set, which means nothing will be written to disk' % utils.color('yellow', 'warning')
        elif args.selection_metric_fname is None and args.action == 'get-selection-metrics' and not args.add_selection_metrics_to_outfname:
            args.selection_metric_fname = utils.insert_before_suffix('-selection-metrics', args.outfname)

    if args.plot_annotation_performance:
        if args.plotdir is None and args.print_n_worst_annotations is None:
            raise Exception('doesn\'t make sense to set --plot-annotation-performance but not either of --plotdir or --print-n-worst-annotations (we\'ll spend all the cycles counting things up but then they\'ll just disappear from memory without being recorded).')
        if not args.is_simu:
            raise Exception('can\'t plot performance unless --is-simu is set (and this is simulation)')
    if args.print_n_worst_annotations is not None and not args.plot_annotation_performance:
        raise Exception('--plot-annotation-performance must be set if you\'re setting --print-worst-annotations')
    if args.action == 'plot-partitions' and args.plotdir is None:
        raise Exception('--plotdir must be specified for plot-partitions')

    if args.make_per_gene_per_base_plots and not args.make_per_gene_plots:  # the former doesn't do anything unless the latter is turned on
        args.make_per_gene_plots = True

    if args.parameter_type != 'hmm':
        print '  using non-default parameter type \'%s\'' % args.parameter_type

    if args.action == 'simulate':
        if args.n_trees is None:
            args.n_trees = max(1, int(float(args.n_sim_events) / args.n_procs))
        if args.n_max_queries != -1:
            print '  note: --n-max-queries is not used when simulating (use --n-sim-events to set the simulated number of rearrangemt events)'

        if args.outfname is None:
            print '  note: no --outfname specified, so nothing will be written to disk'
            args.outfname = get_dummy_outfname(args.workdir)  # hackey, but otherwise I have to rewrite the whole run_simulation() in bin/partis to handle None type outfname UPDATE also if --paired-loci is set, we need the output files for each locus written to disk so we can merge the trees
            if args.paired_loci is not None:
                assert args.light_chain_outfname is None  # wouldn't make sense to set this but not the plain one
                args.light_chain_outfname = get_dummy_outfname(args.workdir, light_chain=True)
        else:
            if args.paired_loci is not None:
                if args.light_chain_outfname is None:
                    raise Exception('if --paired-loci and --outfname are set, you must also set --light-chain-outfname')
                if any(utils.getsuffix(f)=='.csv' for f in [args.outfname, args.light_chain_outfname]):
                    raise Exception('can\'t write paired heavy/light to deprecated .csv output files since pairing requires multi-sequence annotations, but simulation writes .csv files as single-sequence annotations. Use .yaml (really json) output files.')

        if args.paired_loci is not None:
            if args.rearrange_from_scratch or args.mutate_from_scratch:
                raise Exception('--rearrange-from-scratch and --mutate-from-scratch are too complicated to propagate through the automatic --paired-loci infrastructure. If you need these two scratch args, you should run the three steps by hand instead (tree generation, heavy simulation, and light simulation -- run --paired-loci with default parameters to see what these three commands should look like)')
            if args.parameter_dir is not None:
                if args.light_chain_parameter_dir is None:
                    raise Exception('if --paired-loci and --parameter-dir are set, --light-chain-parameter-dir must also be set')

        if args.simulate_from_scratch:
            args.rearrange_from_scratch = True
            args.mutate_from_scratch = True
        if args.rearrange_from_scratch and not args.force_dont_generate_germline_set:  # i would probably just default to always generating germline sets when rearranging from scratch, but bin/test-germline-inference.py (and any other case where you want to dramatically restrict the germline set) really argue for a way to force just using the genes in the germline dir
            args.generate_germline_set = True
        if args.flat_mute_freq or args.same_mute_freq_for_all_seqs:
            assert args.mutate_from_scratch
        if args.mutate_from_scratch and not args.no_per_base_mutation:
            print '  note: setting --no-per-base-mutation since --mutate-from-scratch was set'
            args.no_per_base_mutation = True

        # end result of this block: shm/reco parameter dirs are set (unless we're doing their bit from scratch), --parameter-dir is set to None (and if --parameter-dir was set but shm/reco were _not_ set, we've just used --parameter-dir for either/both as needed)
        if args.parameter_dir is not None:
            if args.rearrange_from_scratch or args.mutate_from_scratch:
                raise Exception('can\'t set --parameter-dir if rearranging or mutating from scratch (use --reco-parameter-dir and/or --shm-parameter-dir)')
            if args.reco_parameter_dir is not None or args.shm_parameter_dir is not None:
                raise Exception('can\'t set --parameter-dir if either --reco-parameter-dir or --shm-parameter-dir are also set')
            args.reco_parameter_dir = args.parameter_dir
            args.shm_parameter_dir = args.parameter_dir
            args.parameter_dir = None
        if args.rearrange_from_scratch and args.reco_parameter_dir is not None:
            raise Exception('doesn\'t make sense to set both --rearrange-from-scratch and --reco-parameter-dir')
        if args.mutate_from_scratch and args.shm_parameter_dir is not None:
            raise Exception('doesn\'t make sense to set both --mutate-from-scratch and --shm-parameter-dir')
        if args.reco_parameter_dir is None and not args.rearrange_from_scratch:
            raise Exception('have to either set --rearrange-from-scratch or --reco-parameter-dir')
        if args.shm_parameter_dir is None and not args.mutate_from_scratch:
            raise Exception('have to either set --mutate-from-scratch or --shm-parameter-dir')

        if args.generate_germline_set and not args.rearrange_from_scratch:
            raise Exception('can only --generate-germline-set if also rearranging from scratch (set --rearrange-from-scratch)')

        if args.generate_germline_set:
            args.snp_positions = None  # if you want to control the exact positions, you have to use bin/test-germline-inference.py
            args.indel_positions = None
            process_gls_gen_args(args)

        if args.generate_trees:
            assert args.n_procs == 1  # not set up to handle output, and also no need

        if args.treefname is not None:
            raise Exception('--treefname was set for simulation action (probably meant to use --input-simulation-treefname)')

    if args.parameter_dir is not None and not args.split_loci:  # if we're splitting loci, this isn't the normal parameter dir, it's a parent of that
        args.parameter_dir = args.parameter_dir.rstrip('/')
        if os.path.exists(args.parameter_dir):
            pdirs = [d for d in os.listdir(args.parameter_dir) if os.path.isdir(d)]
            if len(pdirs) > 0 and len(set(pdirs) & set(parameter_type_choices)) == 0:
                raise Exception('couldn\'t find any expected parameter types (i.e. subdirs) in --parameter-dir \'%s\'. Allowed types: %s, found: %s. Maybe you added the parameter type to the parameter dir path?' % (args.parameter_dir, ' '.join(parameter_type_choices), ' '.join(os.listdir(args.parameter_dir))))

    if os.path.exists(args.default_initial_germline_dir + '/' + args.species):  # ick that is hackey
        args.default_initial_germline_dir += '/' + args.species

    if args.species != 'human' and not args.allele_cluster:
        print '  non-human species \'%s\', turning on allele clustering' % args.species
        args.allele_cluster = True

    if args.n_max_snps is not None and args.n_max_mutations_per_segment is not None:
        if args.n_max_snps > args.n_max_mutations_per_segment - 10:
            raise Exception('--n-max-snps should be at least ten less than --n-max-mutations-per-segment, but I got %d and %d' % (args.n_max_snps, args.n_max_mutations_per_segment))

    if args.leave_default_germline:
        args.dont_remove_unlikely_alleles = True
        args.allele_cluster = False
        args.dont_find_new_alleles = True

    if args.infname is None and args.action not in ['simulate', 'view-output', 'merge-paired-partitions', 'view-annotations', 'view-partitions', 'view-cluster-annotations', 'plot-partitions', 'view-alternative-annotations', 'get-selection-metrics', 'get-linearham-info']:
        raise Exception('--infname is required for action \'%s\'' % args.action)

    if args.action == 'get-linearham-info':
        if args.linearham_info_fname is None:  # for some reason setting required=True isn't working
            raise Exception('have to specify --linearham-info-fname')
        if args.sw_cachefname is None and args.parameter_dir is None:
            raise Exception('have to specify --sw-cachefname or --parameter-dir, since we need sw info to calculate linearham inputs')
        if args.extra_annotation_columns is None or 'linearham-info' not in args.extra_annotation_columns:
            args.extra_annotation_columns = utils.add_lists(args.extra_annotation_columns, ['linearham-info'])

    if args.ete_path is not None and args.ete_path == 'None':  # it's nice to be able to unset this from the command line (so we don't make the slow tree plots)
        args.ete_path = None
