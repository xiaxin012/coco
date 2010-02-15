#! /usr/bin/env python
# -*- coding: utf-8 -*-

"""Helper routines for read index files.
   Defines class IndexEntry, unit element in the post-processing and the list
of instances of IndexEntry: DataSetList.

"""

from __future__ import absolute_import

import os
import re
import pickle
import warnings
from pdb import set_trace
import numpy
from bbob_pproc import findfiles, readalign, bootstrap
from bbob_pproc.readalign import split, alignData, HMultiReader, VMultiReader
from bbob_pproc.readalign import HArrayMultiReader, VArrayMultiReader, alignArrayData

#GLOBAL VARIABLES
idxEvals = 0
idxF = 2
nbPtsF = 5;
indexmainsep = ', '

# CLASS DEFINITIONS
class DataSet:
    """Unit element for the post-processing with given funcId, algId and
    dimension.
    Class attributes:
        funcId -- function Id (integer)
        dim -- dimension (integer)
        indexFiles -- associated index files (list)
        dataFiles -- associated data files (list)
        comment -- comment for the setting (string)
        targetFuncValue -- target function value (float)
        algId -- algorithm name (string)
        evals -- collected data aligned by function values (array)
        funvals -- collected data aligned by function evaluations (array)
        nbRuns -- number of runs (integer)
        maxevals -- maximum number of function evaluations (array)
        finalfunvals -- final function values (array)
        readmaxevals -- maximum number of function evaluations read from index
                        file (array)
        readfinalFminusFtarget -- final function values - ftarget read from
                                  index file (array)
        pickleFile -- associated pickle file name (string)

    evals and funvals are arrays of data collected from N data sets. Both have
    the same format: zero-th column is the value on which the data of a row is
    aligned, the N subsequent columns are either the numbers of function
    evaluations for evals or function values for funvals.
    """

    # Private attribute used for the parsing of info files.
    __attributes = {'funcId': ('funcId', int), 'DIM': ('dim',int),
                    'Precision': ('precision', float), 'Fopt': ('fopt', float),
                    'targetFuncValue': ('targetFuncValue', float),
                    'algId': ('algId', str)}

    def __init__(self, header, comment, data, indexfile, verbose=True):
        """Instantiate an IndexEntry from 3 strings constituting an index
        entry in an index file.

        """

        # Extract information from the header line.
        self.__parseHeader(header)

        # Read in second line of entry (comment line). The information
        # is only stored if the line starts with "%", else it is ignored.
        if comment.startswith('%'):
            self.comment = comment.strip()
        else:
            #raise Exception()
            warnings.warn('Comment line: %s is skipped,' % (comment) +
                          'it does not start with \%.')
            self.comment = ''

        # Split line in data file name(s) and run time information.
        self.indexFiles = [indexfile]
        self.dataFiles = []
        self.itrials = []
        self.evals = []
        self.isFinalized = []
        self.readmaxevals = []
        self.readfinalFminusFtarget = []
        parts = data.split(', ')
        for elem in parts:
            if elem.endswith('dat'):
                #Windows data to Linux processing
                elem = elem.replace('\\', os.sep)
                #Linux data to Windows processing
                elem = elem.replace('/', os.sep)

                self.dataFiles.append(elem)
            else:
                elem = elem.split(':')
                self.itrials.append(int(elem[0]))
                if len(elem) < 2:
                    # Caught a ill-finalized run, in this case, what should we
                    # do? Either we try to process the corresponding data
                    # anyway or we leave it out.
                    # For now we leave it in.
                    self.isFinalized.append(False)
                    warnings.warn('Caught an ill-finalized run in %s for %s'
                                  % (indexfile, self.dataFiles[-1]))
                    self.readmaxevals.append(0)
                    self.readfinalFminusFtarget.append(numpy.inf)
                else:
                    self.isFinalized.append(True)
                    elem = elem[1].split('|')
                    self.readmaxevals.append(int(elem[0]))
                    self.readfinalFminusFtarget.append(float(elem[1]))

        #set_trace()
        if verbose:
            print "%s" % self.__repr__()

        ext = {'.dat':(HMultiReader, 'evals'), '.tdat':(VMultiReader, 'funvals')}
        for extension, info in ext.iteritems():
            dataFiles = list('.'.join(i.split('.')[:-1]) + extension
                             for i in self.dataFiles)
            data = info[0](split(dataFiles))
            if verbose:
                print ("Processing %s: %d/%d trials found."
                       % (dataFiles, len(data), len(self.itrials)))
            (adata, maxevals, finalfunvals) = alignData(data)
            setattr(self, info[1], adata)
            try:
                if all(maxevals > self.maxevals):
                    self.maxevals = maxevals
                    self.finalfunvals = finalfunvals
            except AttributeError:
                self.maxevals = maxevals
                self.finalfunvals = finalfunvals

        # Compute ERT
        self.computeERTfromEvals()
        #set_trace()

    def computeERTfromEvals(self):
        self.ert = []
        self.target = []
        for i in self.evals:
            data = i.copy()
            data = data[1:]
            succ = (numpy.isnan(data)==False)
            if any(numpy.isnan(data)):
                data[numpy.isnan(data)] = self.maxevals[numpy.isnan(data)]
            self.ert.append(bootstrap.sp(data, issuccessful=succ)[0])
            self.target.append(i[0])

        #set_trace()
        self.ert = numpy.array(self.ert)
        self.target = numpy.array(self.target)



    def __eq__(self, other):
        """Compare indexEntry instances."""
        return (self.__class__ is other.__class__ and
                self.funcId == other.funcId and
                self.dim == other.dim and
                #self.precision == other.precision and
                self.algId == other.algId and
                self.comment == other.comment)

    def __ne__(self,other):
        return not self.__eq__(other)

    def __repr__(self):
        return ('{alg: %s, F%d, dim: %d}'
                % (self.algId, self.funcId, self.dim))

    def mMaxEvals(self):
        return max(self.maxevals)

    def nbRuns(self):
        return numpy.shape(self.funvals)[1]-1

    def __parseHeader(self, header):
        """Extract data from a header line in an index entry."""

        # Split header into a list of key-value based on indexmainsep
        headerList = header.split(indexmainsep)

        # Loop over all elements in the list and extract the relevant data.
        # We loop backward to make sure that we did not split inside quotes.
        # It could happen when the key algId and the value is a string.
        p = re.compile('[^,=]+ = .*')
        headerList.reverse()
        it = iter(headerList)
        while True:
            try:
                elem = it.next()
                while not p.match(elem):
                    elem = it.next() + elem

                elemList = elem.split('=')
                #A key name is not expected to contain the string '='
                elemFirst = elemList[0].strip()
                elemSecond = ''.join(elemList[1:]).strip().strip('\'')
                #Here we strip quotes instead of using them to differentiate
                #between data types.

                try:
                    setattr(self, self.__attributes[elemFirst][0],
                            self.__attributes[elemFirst][1](elemSecond))
                except KeyError:
                    warnings.warn('%s is not an expected ' % (elemFirst) +
                                  'attribute.')
                    continue

            except StopIteration:
                break

        #TODO: check that no compulsory attributes is missing:
        #dim, funcId, algId, precision

        return

    def pickle(self, outputdir=None, verbose=True):
        """Save DataSet instance to a pickle file.
        Saves the instance of DataSet to a pickle file. If not specified by
        argument outputdir, the location of the pickle is given by the location
        of the first index file associated to the DataSet.
        """

        # the associated pickle file does not exist
        if not getattr(self, 'pickleFile', False):
            if outputdir is None:
                outputdir = os.path.split(self.indexFiles[0])[0] + '-pickle'
                if not os.path.isdir(outputdir):
                    try:
                        os.mkdir(outputdir)
                    except OSError:
                        print ('Could not create output directory % for pickle files'
                               % outputdir)
                        raise

            self.pickleFile = os.path.join(outputdir,
                                           'ppdata_f%03d_%02d.pickle'
                                            %(self.funcId, self.dim))

        if getattr(self, 'modsFromPickleVersion', True):
            try:
                f = open(self.pickleFile, 'w') # TODO: what if file already exist?
                pickle.dump(self, f)
                f.close()
                if verbose:
                    print 'Saved pickle in %s.' %(self.pickleFile)
            except IOError, (errno, strerror):
                print "I/O error(%s): %s" % (errno, strerror)
            except pickle.PicklingError:
                print "Could not pickle %s" %(self)
        #else: #What?
            #if verbose:
                #print ('Skipped update of pickle file %s: no new data.'
                       #% self.pickleFile)

    def createDictInstance(self):
        """Returns a dictionary of the instances: the key is the instance id,
        the value is a list of index.
        """
        dictinstance = {}
        for i in range(len(self.itrials)):
            dictinstance.setdefault(self.itrials[i], []).append(i)

        return dictinstance


    def splitByTrials(self, whichdata=None):
        """Splits the post-processed data arrays by trials.
        Returns a two-element list of dictionaries of arrays, the key of the
        dictionary being the instance id, the value being a smaller
        post-processed data array corresponding to the instance id.
        """

        dictinstance = self.createDictInstance()
        evals = {}
        funvals = {}

        for instanceid, idx in iteritems(dictinstance):
            evals[instanceid] = self.evals[:,
                                           numpy.ix_(list(i + 1 for i in idx))]
            funvals[instanceid] = self.funvals[:,
                                           numpy.ix_(list(i + 1 for i in idx))]

        if whichdata :
            if whichdata == 'evals':
                return evals
            elif whichdata == 'funvals':
                return funvals

        return (evals, funvals)

class DataSetList(list):
    """Set of instances of DataSet objects, implement some useful slicing
    functions.

    """

    #Do not inherit from set because DataSet instances are mutable.

    def __init__(self, args=[], verbose=True):
        """Instantiate self from a list of inputs.
        Keyword arguments:
        args -- list of strings being either info file names, folder containing
                info files or pickled data files.
        verbose -- controls verbosity.

        Exception:
        Warning -- Unexpected user input.
        pickle.UnpicklingError

        """

        if not args:
            super(DataSetList, self).__init__()
            return

        if isinstance(args, basestring):
            args = [args]

        tmp = []
        for i in args:
            if os.path.isdir(i):
                tmp.extend(findfiles.main(i, verbose))
            else:
                tmp.append(i)

        for i in tmp:
            if i.endswith('.info'):
                self.processIndexFile(i, verbose)
            elif i.endswith('.pickle'):
                try:
                    f = open(i,'r')
                    try:
                        entry = pickle.load(f)
                    except pickle.UnpicklingError:
                        print '%s could not be unpickled.' %(i)
                    f.close()
                    if verbose:
                        print 'Unpickled %s.' % (i)
                    self.append(entry)
                    #set_trace()
                except IOError, (errno, strerror):
                    print "I/O error(%s): %s" % (errno, strerror)

            else:
                warnings.warn('File or folder ' + i + ' not found. ' +
                              'Expecting as input argument either .info ' +
                              'file(s), .pickle file(s) or a folder ' +
                              'containing .info file(s).')


    def processIndexFile(self, indexFile, verbose=True):
        """Reads in an index file information on the different runs."""

        try:
            f = open(indexFile)
            if verbose:
                print 'Processing %s.' % indexFile

            # Read all data sets within one index file.
            indexpath = os.path.split(indexFile)[0]
            nbLine = 1
            while True:
                try:
                    header = f.next()
                    while not header.strip(): # remove blank lines
                        header = f.next()
                        nbLine += 1
                    comment = f.next()
                    if not comment.startswith('%'):
                        warnings.warn('Entry in file %s at line %d is faulty: '
                                      % (indexFile, nbLine) +
                                      'it will be skipped.')
                        nbLine += 2
                        continue
                    tmpline = f.next()
                    nbLine += 3
                    #TODO: check that something is not wrong with the 3 lines.
                    # Add the path to the index file to the file names
                    data = []
                    for i in tmpline.split(indexmainsep):
                        if i.endswith('dat'): #filenames
                            data.append(os.path.join(indexpath, i))
                        else: #other information
                            data.append(i)
                    data = indexmainsep.join(data)
                    self.append(DataSet(header, comment, data, indexFile,
                                        verbose))
                except StopIteration:
                    break

        except IOError:
            print 'Could not open %s.' % indexFile

            # Close index file
            f.close()

    def append(self, o):
        """Redefines the append method to check for unicity."""

        if not isinstance(o, DataSet):
            raise Exception()
        isFound = False
        for i in self:
            if i == o:
                isFound = True
                tmp = set(i.dataFiles).symmetric_difference(set(o.dataFiles))
                #Check if there are new data considered.
                if tmp:
                    i.dataFiles.extend(tmp)
                    i.indexFiles.extend(o.indexFiles)
                    i.funvals = alignArrayData(VArrayMultiReader([i.funvals, o.funvals]))
                    i.finalfunvals = numpy.r_[i.finalfunvals, o.finalfunvals]
                    i.evals = alignArrayData(HArrayMultiReader([i.evals, o.evals]))
                    i.maxevals = numpy.r_[i.maxevals, o.maxevals]
                    i.computeERTfromEvals()
                    if getattr(i, 'pickleFile', False):
                        i.modsFromPickleVersion = True

                    for j in dir(i):
                        if isinstance(getattr(i, j), list):
                            getattr(i, j).extend(getattr(o, j))

                else:
                    if getattr(i, 'pickleFile', False):
                        i.modsFromPickleVersion = False
                    elif getattr(o, 'pickleFile', False):
                        i.modsFromPickleVersion = False
                        i.pickleFile = o.pickleFile
                break
        if not isFound:
            list.append(self, o)

    def extend(self, o):
        """Extend a DataSetList with elements.
        This method is implemented to prevent problems since append was
        superseded. This could be the cause of efficiency issue.
        """

        for i in o:
            self.append(i)

    def pickle(self, outputdir=None, verbose=True):
        """Loop over self to pickle each elements."""

        for i in self:
            i.pickle(outputdir, verbose)

    def dictByAlg(self):
        """Returns a dictionary with algId and comment as keys and
        the corresponding slices of DataSetList as values.
        """

        d = {}
        for i in self:
            d.setdefault((i.algId, i.comment), DataSetList()).append(i)
        return d

    def dictByDim(self):
        """Returns a dictionary with dimension as keys and the corresponding
        slices of DataSetList as values.
        """

        d = {}
        for i in self:
            d.setdefault(i.dim, DataSetList()).append(i)
        return d

    def dictByFunc(self):
        """Returns a dictionary with the function id as keys and the
        corresponding slices of DataSetList as values.
        """

        d = {}
        for i in self:
            d.setdefault(i.funcId, DataSetList()).append(i)
        return d

    def dictByNoise(self):
        """Returns a dictionary splitting noisy and non-noisy entries.
        """

        sorted = {}
        for i in self:
            if i.funcId in range(1, 25):
                sorted.setdefault('noiselessall', DataSetList()).append(i)
            elif i.funcId in range(101, 131):
                sorted.setdefault('nzall', DataSetList()).append(i)
            else:
                warnings.warn('Unknown function id.')

        return sorted

    def dictByFuncGroup(self):
        """Returns a dictionary with function group names as keys and the
        corresponding slices of DataSetList as values.
        """

        sorted = {}
        for i in self:
            if i.funcId in range(1, 6):
                sorted.setdefault('separ', DataSetList()).append(i)
            elif i.funcId in range(6, 10):
                sorted.setdefault('lcond', DataSetList()).append(i)
            elif i.funcId in range(10, 15):
                sorted.setdefault('hcond', DataSetList()).append(i)
            elif i.funcId in range(15, 20):
                sorted.setdefault('multi', DataSetList()).append(i)
            elif i.funcId in range(20, 25):
                sorted.setdefault('mult2', DataSetList()).append(i)
            elif i.funcId in range(101, 107):
                sorted.setdefault('nzmod', DataSetList()).append(i)
            elif i.funcId in range(107, 122):
                sorted.setdefault('nzsev', DataSetList()).append(i)
            elif i.funcId in range(122, 131):
                sorted.setdefault('nzsmm', DataSetList()).append(i)
            else:
                warnings.warn('Unknown function id.')

        return sorted

def processInputArgs(args, plotInfo=None, verbose=True):
    """Process command line arguments into data useable by bbob_pproc scripts
    Returns an instance of DataSetList, a list of algorithms from
    a list of strings representing file and folder names.
    This command will operate folder-wise: one folder will correspond to an
    algorithm.
    It is recommended that if a folder listed in args contain both info files
    and the associated pickle files, they be kept in different locations for
    efficiency reasons.
    Keyword arguments:
      args -- list of string arguments for folder names
      plotInfo -- a dictionary which associates a tuple (algId, comment) to
                  a dictionary to be provided to matplotlib.pyplot.plot
      verbose -- bool controlling verbosity

    Returns: (dsList, sortedAlgs, dictAlg), where
      dsList is a list containing all DataSet instances, this is to prevent the
        regrouping done in instances of DataSetList
      dictAlg is a dictionary which associates algorithms to an instance of
        DataSetList,
      sortedAlgs is the sorted list of keys of dictAlg, the sorting is given
        by the input argument args.
    """

    dsList = list()
    sortedAlgs = list()
    dictAlg = {}

    for i in args:
        if os.path.isfile(i):
            txt = ('The post-processing cannot operate on the single file'
                   + ' %s.' % i)
            warnings.warn(txt)
            continue
        elif os.path.isdir(i):
            tmpDsList = DataSetList(findfiles.main(i, verbose), verbose)
            #Nota: findfiles will find all info AND pickle files in folder i.
            #No problem should arise if the info and pickle files have
            #redundant information. Only, the process could be more efficient
            #if pickle files were in a whole other location.
            dsList.extend(tmpDsList)
            #Find an appropriate name for the algorithm considered?
            #could either refer to dataoutput.plotInfo['label'] or algId
            #tmp = set((i.algId, i.comment) for i in tmpDsList)
            #if not plotInfo is None:
                #alg = plotInfo[tmp.pop()]
            #else:
                #alg = tmp.pop()[0]
            alg = i
            sortedAlgs.append(alg)
            dictAlg[alg] = tmpDsList
        else:
            txt = 'Input folder %s could not be found.'
            #raise Usage(txt) #TODO how to call Usage?
            warnings.warn(txt)

    return dsList, sortedAlgs, dictAlg

def dictAlgByDim(dictAlg):
    res = {}
    dims = set()
    tmpdictAlg = {}
    for alg, dsList in dictAlg.iteritems():
        tmp = dsList.dictByDim()
        tmpdictAlg[alg] = tmp
        dims |= set(tmp.keys())

    for d in dims:
        for alg in dictAlg:
            tmp = DataSetList()
            try:
                tmp = tmpdictAlg[alg][d]
            except KeyError:
                txt = ('No data for algorithm %s in %d-D.'
                       % (alg, d))
                warnings.warn(txt)

            if res.setdefault(d, {}).has_key(alg):
                txt = ('Duplicate data for algorithm %s in %d-D.'
                       % (alg, d))
                warnings.warn(txt)

            res.setdefault(d, {}).setdefault(alg, tmp)
            # Only the first data for a given algorithm in a given dimension

    return res

def dictAlgByFun(dictAlg):
    res = {}
    funcs = set()
    tmpdictAlg = {}
    for alg, dsList in dictAlg.iteritems():
        tmp = dsList.dictByFunc()
        tmpdictAlg[alg] = tmp
        funcs |= set(tmp.keys())

    for f in funcs:
        for alg in dictAlg:
            tmp = DataSetList()
            try:
                tmp = tmpdictAlg[alg][f]
            except KeyError:
                txt = ('No data for algorithm %s on function %d.'
                       % (alg, f))
                warnings.warn(txt)

            if res.setdefault(f, {}).has_key(alg):
                txt = ('Duplicate data for algorithm %s on function %d-D.'
                       % (alg, f))
                warnings.warn(txt)

            res.setdefault(f, {}).setdefault(alg, tmp)
            # Only the first data for a given algorithm in a given dimension

    return res

def dictAlgByNoi(dictAlg):
    res = {}
    ng = set()
    tmpdictAlg = {}
    for alg, dsList in dictAlg.iteritems():
        tmp = dsList.dictByNoise()
        tmpdictAlg[alg] = tmp
        ng |= set(tmp.keys())

    for n in ng:
        stmp = ''
        if n == 'nzall':
            stmp = 'noisy'
        elif n == 'noiselessall':
            stmp = 'noiseless'

        for alg in dictAlg:
            tmp = DataSetList()
            try:
                tmp = tmpdictAlg[alg][n]
            except KeyError:
                txt = ('No data for algorithm %s on %s function.'
                       % (alg, stmp))
                warnings.warn(txt)

            if res.setdefault(n, {}).has_key(alg):
                txt = ('Duplicate data for algorithm %s on %s functions.'
                       % (alg, stmp))
                warnings.warn(txt)

            res.setdefault(n, {}).setdefault(alg, tmp)
            # Only the first data for a given algorithm in a given dimension

    return res
