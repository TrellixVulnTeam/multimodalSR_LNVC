from __future__ import print_function

import logging  # debug < info < warn < error < critical  # from https://docs.python.org/3/howto/logging-cookbook.html
import math
import os
import time
import traceback

import lasagne
import lasagne.layers as L
import theano
import theano.tensor as T
from tqdm import tqdm
import traceback


logger_RNNtools = logging.getLogger('audioSR.tools')
logger_RNNtools.setLevel(logging.DEBUG)

from general_tools import *
import preprocessingCombined


class NeuralNetwork:
    network = None
    training_fn = None
    best_param = None
    best_error = 100
    curr_epoch, best_epoch = 0, 0
    X = None
    Y = None


    def __init__(self, architecture, dataset=None, batch_size=1, max_seq_length=1000, num_features=26, n_hidden_list=(100,), num_output_units=61,
                 bidirectional=False, addDenseLayers=False, seed=int(time.time()), debug=False, logger=logger_RNNtools):
        self.num_output_units = num_output_units
        self.num_features = num_features
        self.batch_size = batch_size
        self.max_seq_length = max_seq_length #currently unused
        self.epochsNotImproved = 0  #keep track, to know when to stop training
        self.updates = {}
        # self.network_train_info = [[], [], [], [], []]  # train cost, val cost, val acc, test cost, test acc
        self.network_train_info = {
            'train_cost': [],
            'val_cost':   [], 'val_acc': [], 'val_topk_acc': [],
            'test_cost':  [], 'test_acc': [], 'test_topk_acc': []
        }

        if architecture == 'RNN':
            if dataset != None:
                images_train, mfccs_train, audioLabels_train, validLabels_train, validAudioFrames_train = dataset

                self.mfccs = mfccs_train[:batch_size]
                self.audioLabels = audioLabels_train[:batch_size]
                self.validLabels = validLabels_train[:batch_size]
                self.validAudioFrames = validAudioFrames_train[:batch_size]

                self.masks = generate_masks(inputs=self.mfccs, valid_frames=self.validAudioFrames,
                                            batch_size=len(self.mfccs), logger=logger_RNNtools)

                self.X = pad_sequences_X(self.mfccs)
                self.Y = pad_sequences_y(self.audioLabels) # Y needs all the audio labels, not just the valid ones
                self.validAudioFrames = pad_sequences_y(self.validAudioFrames)

                logger.debug('X.shape:          %s', self.X.shape)
                logger.debug('X[0].shape:       %s', self.X[0].shape)
                logger.debug('X[0][0][0].type:  %s', type(self.X[0][0][0]))
                logger.debug('y.shape:          %s', self.Y.shape)
                logger.debug('y[0].shape:       %s', self.Y[0].shape)
                logger.debug('y[0][0].type:     %s', type(self.Y[0][0]))
                logger.debug('masks.shape:      %s', self.masks.shape)
                logger.debug('masks[0].shape:   %s', self.masks[0].shape)
                logger.debug('masks[0][0].type: %s', type(self.masks[0][0]))

                #import pdb;pdb.set_trace()

            logger.info("NUM FEATURES: %s", num_features)

            self.audio_inputs_var = T.tensor3('audio_inputs')
            self.audio_masks_var = T.matrix('audio_masks')  # set MATRIX, not iMatrix!! Otherwise all mask calculations are done by CPU, and everything will be ~2x slowed down!! Also in general_tools.generate_masks()
            self.audio_valid_indices_var = T.imatrix('audio_valid_indices')
            self.audio_targets_var = T.imatrix('audio_targets')

            self.build_RNN(n_hidden_list=n_hidden_list,  bidirectional=bidirectional, addDenseLayers=addDenseLayers,
                           seed=seed, debug=debug, logger=logger)
        else:
            print("ERROR: Invalid argument: The valid architecture arguments are: 'RNN'")

    def build_RNN(self, n_hidden_list=(100,), bidirectional=False, addDenseLayers=False,
                  seed=int(time.time()), debug=False, logger=logger_RNNtools):
        # some inspiration from http://colinraffel.com/talks/hammer2015recurrent.pdf

        # if debug:
        #     logger_RNNtools.debug('\nInputs:');
        #     logger_RNNtools.debug('  X.shape:    %s', self.X[0].shape)
        #     logger_RNNtools.debug('  X[0].shape: %s %s %s \n%s', self.X[0][0].shape, type(self.X[0][0]),
        #                           type(self.X[0][0][0]), self.X[0][0][:5])
        #
        #     logger_RNNtools.debug('Targets: ');
        #     logger_RNNtools.debug('  Y.shape:    %s', self.Y.shape)
        #     logger_RNNtools.debug('  Y[0].shape: %s %s %s \n%s', self.Y[0].shape, type(self.Y[0]), type(self.Y[0][0]),
        #                           self.Y[0][:5])
        #     logger_RNNtools.debug('Layers: ')

        # fix these at initialization because it allows for compiler opimizations
        num_output_units = self.num_output_units
        num_features = self.num_features
        batch_size = self.batch_size

        audio_inputs = self.audio_inputs_var
        audio_masks = self.audio_masks_var       #set MATRIX, not iMatrix!! Otherwise all mask calculations are done by CPU, and everything will be ~2x slowed down!! Also in general_tools.generate_masks()
        valid_indices = self.audio_valid_indices_var
        
        
        net = {}
        # net['l1_in_valid'] = L.InputLayer(shape=(batch_size, None), input_var=valid_indices)

        # shape = (batch_size, batch_max_seq_length, num_features)
        net['l1_in'] = L.InputLayer(shape=(batch_size, None, num_features),input_var=audio_inputs)
        # We could do this and set all input_vars to None, but that is slower -> fix batch_size and num_features at initialization
        # batch_size, n_time_steps, n_features = net['l1_in'].input_var.shape

        # This input will be used to provide the network with masks.
        # Masks are matrices of shape (batch_size, n_time_steps);
        net['l1_mask'] = L.InputLayer(shape=(batch_size, None), input_var=audio_masks)

        if debug:
            get_l_in = L.get_output(net['l1_in'])
            l_in_val = get_l_in.eval({net['l1_in'].input_var: self.X})
            # logger_RNNtools.debug(l_in_val)
            logger_RNNtools.debug('  l_in size: %s', l_in_val.shape);

            get_l_mask = L.get_output(net['l1_mask'])
            l_mask_val = get_l_mask.eval({net['l1_mask'].input_var: self.masks})
            # logger_RNNtools.debug(l_in_val)
            logger_RNNtools.debug('  l_mask size: %s', l_mask_val.shape);

            n_batch, n_time_steps, n_features = net['l1_in'].input_var.shape
            logger_RNNtools.debug("  n_batch: %s | n_time_steps: %s | n_features: %s", n_batch, n_time_steps,
                                  n_features)

        ## LSTM parameters
        # All gates have initializers for the input-to-gate and hidden state-to-gate
        # weight matrices, the cell-to-gate weight vector, the bias vector, and the nonlinearity.
        # The convention is that gates use the standard sigmoid nonlinearity,
        # which is the default for the Gate class.
        gate_parameters = L.recurrent.Gate(
                W_in=lasagne.init.Orthogonal(), W_hid=lasagne.init.Orthogonal(),
                b=lasagne.init.Constant(0.))
        cell_parameters = L.recurrent.Gate(
                W_in=lasagne.init.Orthogonal(), W_hid=lasagne.init.Orthogonal(),
                # Setting W_cell to None denotes that no cell connection will be used.
                W_cell=None, b=lasagne.init.Constant(0.),
                # By convention, the cell nonlinearity is tanh in an LSTM.
                nonlinearity=lasagne.nonlinearities.tanh)

        # generate layers of stacked LSTMs, possibly bidirectional
        net['l2_lstm'] = []

        for i in range(len(n_hidden_list)):
            n_hidden = n_hidden_list[i]

            if i==0: input = net['l1_in']
            else:    input = net['l2_lstm'][i-1]

            nextForwardLSTMLayer = L.recurrent.LSTMLayer(
                    input, n_hidden,
                    # We need to specify a separate input for masks
                    mask_input=net['l1_mask'],
                    # Here, we supply the gate parameters for each gate
                    ingate=gate_parameters, forgetgate=gate_parameters,
                    cell=cell_parameters, outgate=gate_parameters,
                    # We'll learn the initialization and use gradient clipping
                    learn_init=True, grad_clipping=100.)
            net['l2_lstm'].append(nextForwardLSTMLayer)

            if bidirectional:
                input = net['l2_lstm'][-1]
                # Use backward LSTM
                # The "backwards" layer is the same as the first,
                # except that the backwards argument is set to True.
                nextBackwardLSTMLayer = L.recurrent.LSTMLayer(
                        input, n_hidden, ingate=gate_parameters,
                        mask_input=net['l1_mask'], forgetgate=gate_parameters,
                        cell=cell_parameters, outgate=gate_parameters,
                        learn_init=True, grad_clipping=100., backwards=True)
                net['l2_lstm'].append(nextBackwardLSTMLayer)

                # if debug:
                #     # Backwards LSTM
                #     get_l_lstm_back = theano.function([net['l1_in'].input_var, net['l1_mask'].input_var],
                #                                       L.get_output(net['l2_lstm'][-1]))
                #     l_lstmBack_val = get_l_lstm_back(self.X, self.masks)
                #     logger_RNNtools.debug('  l_lstm_back size: %s', l_lstmBack_val.shape)

                # We'll combine the forward and backward layer output by summing.
                # Merge layers take in lists of layers to merge as input.
                # The output of l_sum will be of shape (n_batch, max_n_time_steps, n_features)
                net['l2_lstm'].append(L.ElemwiseSumLayer([net['l2_lstm'][-2], net['l2_lstm'][-1]]))

        # we need to convert (batch_size, seq_length, num_features) to (batch_size * seq_length, num_features) because Dense networks can't deal with 2 unknown sizes
        net['l3_reshape'] = L.ReshapeLayer(net['l2_lstm'][-1], (-1, n_hidden_list[-1]))

        # if debug:
        #     get_l_reshape = theano.function([net['l1_in'].input_var, net['l1_mask'].input_var],
        #                                     L.get_output(net['l3_reshape']))
        #     l_reshape_val = get_l_reshape(self.X, self.masks)
        #     logger.debug('  l_reshape size: %s', l_reshape_val.shape)
        #
        # if debug:
        #     # Forwards LSTM
        #     get_l_lstm = theano.function([net['l1_in'].input_var, net['l1_mask'].input_var],
        #                                  L.get_output(net['l2_lstm'][-1]))
        #     l_lstm_val = get_l_lstm(self.X, self.masks)
        #     logger_RNNtools.debug('  l2_lstm size: %s', l_lstm_val.shape);

        if addDenseLayers:
            net['l4_dense'] = L.DenseLayer(net['l3_reshape'], nonlinearity =lasagne.nonlinearities.rectify, num_units=256)
            dropoutLayer = L.DropoutLayer(net['l4_dense'], p=0.3)
            net['l5_dense'] = L.DenseLayer(dropoutLayer, nonlinearity=lasagne.nonlinearities.rectify, num_units=64)
            # Now we can apply feed-forward layers as usual for classification
            net['l6_dense'] = L.DenseLayer(net['l5_dense'], num_units=num_output_units,
                                           nonlinearity=lasagne.nonlinearities.softmax)
        else:
            # Now we can apply feed-forward layers as usual for classification
            net['l6_dense'] = L.DenseLayer(net['l3_reshape'], num_units=num_output_units,
                                           nonlinearity=lasagne.nonlinearities.softmax)

        # # Now, the shape will be (n_batch * n_timesteps, num_output_units). We can then reshape to
        # # n_batch to get num_output_units values for each timestep from each sequence
        net['l7_out_flattened'] = L.ReshapeLayer(net['l6_dense'], (-1, num_output_units))
        net['l7_out'] = L.ReshapeLayer(net['l6_dense'], (batch_size, -1, num_output_units))
        
        net['l7_out_valid_basic'] = L.SliceLayer(net['l7_out'], indices=valid_indices, axis=1)
        net['l7_out_valid'] = L.ReshapeLayer(net['l7_out_valid_basic'],(batch_size, -1, num_output_units))
        net['l7_out_valid_flattened'] = L.ReshapeLayer(net['l7_out_valid_basic'], (-1, num_output_units))

        if debug:
            get_l_out = theano.function([net['l1_in'].input_var, net['l1_mask'].input_var], L.get_output(net['l7_out']))
            l_out = get_l_out(self.X, self.masks)

            # this only works for batch_size == 1
            get_l_out_valid = theano.function([audio_inputs, audio_masks, valid_indices],
                                         L.get_output(net['l7_out_valid']))
            try:
                l_out_valid = get_l_out_valid(self.X, self.masks, self.valid_frames)
                logger_RNNtools.debug('\n\n\n  l_out: %s  | l_out_valid: %s', l_out.shape, l_out_valid.shape);
            except: logger_RNNtools.warning("batchsize not 1, get_valid not working")


        if debug:   self.print_network_structure(net)
        self.network_lout = net['l7_out_flattened']
        self.network_lout_batch = net['l7_out']
        self.network_lout_valid = net['l7_out_valid']
        self.network_lout_valid_flattened = net['l7_out_valid_flattened']

        self.network = net

    def print_network_structure(self, net=None, logger=logger_RNNtools):
        if net==None: net = self.network

        logger.debug("\n PRINTING Network structure: \n %s ", sorted(net.keys()))
        for key in sorted(net.keys()):
            if 'lstm' in key:
                for layer in net['l2_lstm']:
                    try:
                        logger.debug('Layer: %12s | in: %s | out: %s', key, layer.input_shape, layer.output_shape)
                    except:
                        logger.debug('Layer: %12s | out: %s', key, layer.output_shape)
            else:
                try:
                    logger.debug('Layer: %12s | in: %s | out: %s', key, net[key].input_shape, net[key].output_shape)
                except:
                    logger.debug('Layer: %12s | out: %s', key, net[key].output_shape)
        return 0

    def use_best_param(self):
        L.set_all_param_values(self.network, self.best_param)
        self.curr_epoch = self.best_epoch
        # Remove the network_train_info enries newer than self.best_epoch
        del self.network_train_info[0][self.best_epoch:]
        del self.network_train_info[1][self.best_epoch:]
        del self.network_train_info[2][self.best_epoch:]

    def load_model(self, model_name, logger=logger_RNNtools):
        if self.network is not None:
            try:
                logger.info("Loading stored model...")

                # restore network weights
                with np.load(model_name) as f:
                    param_values = [f['arr_%d' % i] for i in range(len(f.files))]
                    L.set_all_param_values(self.network_lout, *param_values)

                # # restore 'updates' training parameters
                # with np.load(model_name + "_updates.npz") as f:
                #     updates_values = [f['arr_%d' % i] for i in range(len(f.files))]
                #     for p, value in zip(self.updates.keys(), updates_values):
                #         p.set_value(value)
                logger.info("Loading parameters successful.")
                return 0

            except IOError as e:
                print(os.strerror(e.errno))
                logger.warning('Model: {} not found. No weights loaded'.format(model_name))
                return -1
        else:
            raise IOError('You must build the network before loading the weights.')
        return -1

    def save_model(self, model_name, logger=logger_RNNtools):
        if not os.path.exists(os.path.dirname(model_name)):
            os.makedirs(os.path.dirname(model_name))
        np.savez(model_name + '.npz', self.best_param)

        # also restore the updates variables to continue training. LR should also be saved and restored...
        # updates_vals = [p.get_value() for p in self.best_updates.keys()]
        # np.savez(model_name + '_updates.npz', updates_vals)

    def create_confusion(self, X, y, debug=False, logger=logger_RNNtools):
        argmax_fn = self.training_fn[1]

        y_pred = []
        for X_obs in X:
            for x in argmax_fn(X_obs):
                for j in x:
                    y_pred.append(j)

        y_actu = []
        for Y in y:
            for y in Y:
                y_actu.append(y)

        conf_img = np.zeros([61, 61])
        assert (len(y_pred) == len(y_actu))

        for i in range(len(y_pred)):
            row_idx = y_actu[i]
            col_idx = y_pred[i]
            conf_img[row_idx, col_idx] += 1

        return conf_img, y_pred, y_actu

    def build_functions(self, train=False, debug=False, logger=logger_RNNtools):

        # LSTM in lasagne: see https://github.com/craffel/Lasagne-tutorial/blob/master/examples/recurrent.py
        # and also         http://colinraffel.com/talks/hammer2015recurrent.pdf
        target_var = self.audio_targets_var #T.imatrix('audio_targets')

        # if debug:  import pdb; self.print_network_structure()

        batch = True
        if batch:
            network_output = L.get_output(self.network_lout_batch)
            network_output_flattened = L.get_output(self.network_lout)  # (batch_size * batch_max_seq_length, nb_phonemes)

            # compare targets with highest output probability. Take maximum of all probs (3rd axis (index 2) of output: 1=batch_size (input files), 2 = time_seq (frames), 3 = n_features (phonemes)
            # network_output.shape = (len(X), 39) -> (nb_inputs, nb_classes)
            predictions = (T.argmax(network_output, axis=2))
            self.predictions_fn = theano.function([self.audio_inputs_var, self.audio_masks_var], predictions,
                                                  name='predictions_fn')

            if debug:
                predicted = self.predictions_fn(self.X, self.masks)
                logger.debug('predictions_fn(X).shape: %s', predicted.shape)
                # logger.debug('predictions_fn(X)[0], value: %s', predicted[0])

            if debug:
                self.output_fn = theano.function([self.audio_inputs_var, self.audio_masks_var], network_output, name='output_fn')
                n_out = self.output_fn(self.X, self.masks)
                logger.debug('network_output.shape: \t%s', n_out.shape);
                # logger.debug('network_output[0]:     \n%s', n_out[0]);

            # # Function to determine the number of correct classifications
            valid_indices_example, valid_indices_seqNr = self.audio_masks_var.nonzero()
            valid_indices_fn = theano.function([self.audio_masks_var], [valid_indices_example, valid_indices_seqNr], name='valid_indices_fn')

            # this gets a FLATTENED array of all the valid predictions of all examples of this batch (so not one row per example)
            # if you want to get the valid predictions per example, you need to use the valid_frames list (it tells you the number of valid frames per wav, so where to split this valid_predictions array)
            # of course this is trivial for batch_size_audio = 1, as all valid_predictions will belong to the one input wav
            valid_predictions = predictions[valid_indices_example, valid_indices_seqNr]
            valid_targets = target_var[valid_indices_example, valid_indices_seqNr]
            self.valid_targets_fn = theano.function([self.audio_masks_var, target_var], valid_targets, name='valid_targets_fn')
            self.valid_predictions_fn = theano.function([self.audio_inputs_var, self.audio_masks_var], valid_predictions, name='valid_predictions_fn')

            # using the lasagne SliceLayer
            valid_network_output2 = L.get_output(self.network['l7_out_valid'])
            self.valid_network_fn = theano.function([self.audio_inputs_var, self.audio_masks_var,
                                                     self.audio_valid_indices_var], valid_network_output2)
            valid_network_output_flattened = L.get_output(self.network_lout_valid_flattened)

            valid_predictions2 = T.argmax(valid_network_output2,axis=2)
            self.valid_predictions2_fn = theano.function(
                    [self.audio_inputs_var, self.audio_masks_var, self.audio_valid_indices_var],
                    valid_predictions2, name='valid_predictions_fn')

            # if debug:
            #     try:
            #         valid_preds2 = self.valid_predictions2_fn(self.X, self.masks, self.validAudioFrames)
            #         logger.debug("all valid predictions of this batch: ")
            #         logger.debug('valid_preds2.shape: %s', valid_preds2.shape)
            #         logger.debug('valid_preds2, value: \n%s', valid_preds2)
            #
            #         valid_example, valid_seqNr = valid_indices_fn(self.masks)
            #         logger.debug('valid_inds(masks).shape: %s', valid_example.shape)
            #         valid_preds = self.valid_predictions_fn(self.X, self.masks)
            #         logger.debug("all valid predictions of this batch: ")
            #         logger.debug('valid_preds.shape: %s', valid_preds.shape)
            #         logger.debug('valid_preds, value: \n%s', valid_preds)
            #
            #         valid_targs = self.valid_targets_fn(self.masks, self.Y)
            #         logger.debug('valid_targets.shape: %s', valid_targs.shape)
            #         logger.debug('valid_targets, value: \n%s', valid_targs)
            #
            #         valid_out = self.valid_network_fn(self.X, self.masks, self.validAudioFrames)
            #         logger.debug('valid_out.shape: %s', valid_out.shape)
            #         # logger.debug('valid_out, value: \n%s', valid_out)
            #
            #         try:
            #             # Functions for computing cost and training
            #             top1_acc = T.mean(lasagne.objectives.categorical_accuracy(
            #                     valid_network_output_flattened, valid_targets,  top_k=1))
            #             self.top1_acc_fn = theano.function(
            #                     [self.audio_inputs_var, self.audio_masks_var, self.audio_valid_indices_var,
            #                      self.audio_targets_var], top1_acc)
            #             top3_acc = T.mean(lasagne.objectives.categorical_accuracy(
            #                     valid_network_output_flattened, valid_targets, top_k=3))
            #             self.top3_acc_fn = theano.function(
            #                     [self.audio_inputs_var, self.audio_masks_var, self.audio_valid_indices_var,
            #                      self.audio_targets_var], top3_acc)
            #
            #             top1 = self.top1_acc_fn(self.X, self.masks, self.validAudioFrames, self.Y)
            #             logger.debug("top 1 accuracy: %s", top1*100.0)
            #
            #             top3 = self.top3_acc_fn(self.X, self.masks, self.validAudioFrames, self.Y)
            #             logger.debug("top 3 accuracy: %s", top3*100.0)
            #         except Exception as e:
            #             print('caught this error: ' + traceback.format_exc());
            #             import pdb;                        pdb.set_trace()
            #
            #     except Exception as error:
            #         print('caught this error: ' + traceback.format_exc());
            #         import pdb;pdb.set_trace()
            #     #pdb.set_trace()

            # only use the output at the middle of each phoneme interval (get better accuracy)
            # Accuracy => # (correctly predicted & valid frames) / #valid frames
            validAndCorrect = T.sum(T.eq(valid_predictions, valid_targets),dtype='float32')
            nbValidFrames = T.sum(self.audio_masks_var)
            accuracy =  validAndCorrect / nbValidFrames

        else:
            # Function to get the output of the network
            # network_output = L.get_output(self.network_lout_batch)                     # (batch_size, batch_max_seq_length, nb_phonemes)
            network_output_flattened = L.get_output(self.network_lout) # (batch_size * batch_max_seq_length, nb_phonemes)

            # valid predictions
            eqs = T.neq(self.audio_masks_var.flatten(), T.zeros((1,)))
            valid_indices = eqs.nonzero()[0]
            valid_indices_fn = theano.function([self.audio_masks_var], valid_indices, name='valid_indices_fn')
            valid_predictions = network_output_flattened[valid_indices, :]
            self.valid_predictions_fn = theano.function([self.audio_inputs_var, self.audio_masks_var], valid_predictions,
                                                        name='valid_predictions_fn')

            # the flattened version; faster because we need flattened stuff anyway when calculating loss.
            # If we used the batched version here, we would need to calculate both batched and flattened predictions, which is double work.
            predictions_flattened = (T.argmax(network_output_flattened, axis=1))
            self.predictions_fn = theano.function([self.audio_inputs_var, self.audio_masks_var], predictions_flattened,
                                                  name='predictions_fn')
            validAndCorrect = T.sum(T.eq(predictions_flattened, target_var.flatten()) * self.audio_masks_var.flatten())
            nbValidFrames = T.sum(self.audio_masks_var.flatten())
            accuracy = validAndCorrect / nbValidFrames


        ## from https://groups.google.com/forum/#!topic/lasagne-users/os0j3f_Th5Q
        # Pad your vector of labels and then mask the cost:
        # It's important to pad the label vectors with something valid such as zeros,
        # since they will still have to give valid costs that can be multiplied by the mask.
        # The shape of predictions, targets and mask should match:
        # (predictions as (batch_size*max_seq_len, n_features), the other two as (batch_size*max_seq_len,)) -> we need to get the flattened output of the network for this

        # this works, using theano masks
        try:cost_pointwise = lasagne.objectives.categorical_crossentropy(network_output_flattened, target_var.flatten())
        except:
            print('caught this error: ' + traceback.format_exc());
            import pdb;    pdb.set_trace()
        cost = lasagne.objectives.aggregate(cost_pointwise, self.audio_masks_var.flatten())

        # # Top k accuracy
        top3_acc = T.mean(lasagne.objectives.categorical_accuracy(
                valid_predictions, valid_targets, top_k=3))

        self.validate_fn = theano.function([self.audio_inputs_var, self.audio_masks_var, self.audio_targets_var],
                                      [cost, accuracy, top3_acc], name='validate_fn')
        self.cost_pointwise_fn = theano.function([self.audio_inputs_var, self.audio_masks_var, target_var],
                                            cost_pointwise, name='cost_pointwise_fn')


        if debug:
            try:logger.debug('cost pointwise: %s', self.cost_pointwise_fn(self.X, self.masks, self.Y))
            except:
                print('caught this error: ' + traceback.format_exc());
                import pdb; pdb.set_trace()

            try:evaluate_cost = self.validate_fn(self.X, self.masks, self.Y)
            except:
                print('caught this error: ' + traceback.format_exc()); import pdb;pdb.set_trace()
            logger.debug('evaluate_cost: %s %s', type(evaluate_cost), len(evaluate_cost))
            logger.debug('%s', evaluate_cost)
            logger.debug('cost:     {:.3f}'.format(float(evaluate_cost[0])))
            logger.debug('accuracy: {:.3f}'.format(float(evaluate_cost[1])))
            #pdb.set_trace()

        if train:
            LR = T.scalar('LR', dtype=theano.config.floatX)
            # Retrieve all trainable parameters from the network
            all_params = L.get_all_params(self.network_lout, trainable=True)
            self.updates = lasagne.updates.adam(loss_or_grads=cost, params=all_params, learning_rate=LR)
            self.train_fn = theano.function([self.audio_inputs_var, self.audio_masks_var, target_var, LR],
                                       cost, updates=self.updates, name='train_fn')

    def shuffle(self, lst):
        import random
        c = list(zip(*lst))
        random.shuffle(c)
        shuffled = zip(*c)
        for i in range(len(shuffled)):
            shuffled[i] = list(shuffled[i])
        return shuffled

    # This function trains the model a full epoch (on the whole dataset)
    def train_epoch(self, mfccs, validLabels, valid_frames, LR, batch_size=-1):
        if batch_size == -1: batch_size = self.batch_size

        cost = 0;
        nb_batches = len(mfccs) / batch_size

        for i in tqdm(range(nb_batches), total=nb_batches):
            batch_mfccs = mfccs[i * batch_size:(i + 1) * batch_size]
            batch_validLabels = validLabels[i * batch_size:(i + 1) * batch_size]
            batch_valid_frames = valid_frames[i * batch_size:(i + 1) * batch_size]
            batch_masks = generate_masks(batch_mfccs, valid_frames=batch_valid_frames, batch_size=batch_size)
            # now pad inputs and target to maxLen
            batch_mfccs = pad_sequences_X(batch_mfccs)
            batch_valid_frames = pad_sequences_y(batch_valid_frames)
            batch_validLabels = pad_sequences_y(batch_validLabels)
            # print("batch_mfccs.shape: ", batch_mfccs.shape)
            # print("batch_validLabels.shape: ", batch_validLabels.shape)
            cst = self.train_fn(batch_mfccs, batch_masks, batch_validLabels, LR)  # training
            cost += cst;

        return cost, nb_batches

    # This function trains the model a full epoch (on the whole dataset)
    def val_epoch(self, mfccs, validLabels, valid_frames, batch_size=-1):
        if batch_size == -1: batch_size = self.batch_size

        cost = 0;
        accuracy = 0
        top3_accuracy = 0
        nb_batches = len(mfccs) / batch_size

        for i in tqdm(range(nb_batches), total=nb_batches):
            batch_mfccs = mfccs[i * batch_size:(i + 1) * batch_size]
            batch_validLabels = validLabels[i * batch_size:(i + 1) * batch_size]
            batch_valid_frames = valid_frames[i * batch_size:(i + 1) * batch_size]
            batch_masks = generate_masks(batch_mfccs, valid_frames=batch_valid_frames, batch_size=batch_size)
            # now pad inputs and target to maxLen
            batch_mfccs = pad_sequences_X(batch_mfccs)
            batch_valid_frames = pad_sequences_y(batch_valid_frames)
            batch_validLabels = pad_sequences_y(batch_validLabels)
            # print("batch_mfccs.shape: ", batch_mfccs.shape)
            # print("batch_validLabels.shape: ", batch_validLabels.shape)
            cst, acc, top3_acc = self.validate_fn(batch_mfccs, batch_masks, batch_validLabels)  # training
            cost += cst;
            accuracy += acc
            top3_accuracy += top3_acc

        return cost, accuracy, top3_accuracy, nb_batches


    # evaluate many TRAINING speaker files -> train loss, val loss and val error. Load them in one by one (so they fit in memory)
    def evalTRAINING(self, trainingSpeakerFiles, LR, shuffleEnabled=True, sourceDataDir=None,
                     storeProcessed=False, processedDir=None, verbose=False, logger=logger_RNNtools):
        train_cost = 0;
        val_acc = 0;
        val_cost = 0;
        val_topk_acc = 0;
        nb_train_batches = 0;
        nb_val_batches = 0;

        # for each speaker, pass over the train set, then val set. (test is other files). save the results.
        for speakerFile in tqdm(trainingSpeakerFiles, total=len(trainingSpeakerFiles)):
            logger.debug("processing %s", speakerFile)
            train, val, test = preprocessingCombined.getOneSpeaker(
                    speakerFile=speakerFile, sourceDataDir=sourceDataDir,
                    trainFraction=0.8, validFraction=0.2,
                    storeProcessed=storeProcessed, processedDir=processedDir, logger=logger)

            if shuffleEnabled: train = self.shuffle(train)
            images_train, mfccs_train, audioLabels_train, validLabels_train, validAudioFrames_train = train
            images_val, mfccs_val, audioLabels_val, validLabels_val, validAudioFrames_val = val
            images_test, mfccs_test, audioLabels_test, validLabels_test, validAudioFrames_test = test

            if verbose:
                logger.debug("the number of training examples is: %s", len(images_train))
                logger.debug("the number of valid examples is:    %s", len(images_val))
                logger.debug("the number of test examples is:     %s", len(images_test))

            train_cost_one, train_batches_one = self.train_epoch(mfccs=mfccs_train,
                                                                 validLabels=audioLabels_train,
                                                                 valid_frames=validAudioFrames_train,
                                                                 LR=LR)
            train_cost += train_cost_one;
            nb_train_batches += train_batches_one

            # get results for validation  set
            val_cost_one, val_acc_one, val_topk_acc_one, val_batches_one = self.val_epoch(mfccs=mfccs_val,
                                                                                          validLabels=audioLabels_val,
                                                                                          valid_frames=validAudioFrames_val)
            val_cost += val_cost_one;
            val_acc += val_acc_one;
            val_topk_acc += val_topk_acc_one
            nb_val_batches += val_batches_one;

            if verbose:
                logger.debug("  this speaker results: ")
                logger.debug("\ttraining cost:     %s", train_cost_one / train_batches_one)
                logger.debug("\tvalidation cost:   %s", val_cost_one / val_batches_one)
                logger.debug("\vvalidation acc rate:  %s %%", val_acc_one / val_batches_one * 100)
                logger.debug("\vvalidation top 3 acc rate:  %s %%", val_topk_acc_one / val_batches_one * 100)

        # get the average over all speakers
        train_cost /= nb_train_batches
        val_cost /= nb_val_batches
        val_acc = val_acc / nb_val_batches * 100  # convert to %
        val_topk_acc = val_topk_acc / nb_val_batches * 100  # convert to %

        return train_cost, val_cost, val_acc, val_topk_acc

    def evalTEST(self, testSpeakerFiles, sourceDataDir=None, storeProcessed=False, processedDir=None,
                 verbose=False, logger=logger_RNNtools):

        test_acc = 0;
        test_cost = 0;
        test_topk_acc = 0;
        nb_test_batches = 0;
        # for each speaker, pass over the train set, then test set. (test is other files). save the results.
        for speakerFile in tqdm(testSpeakerFiles, total=len(testSpeakerFiles)):
            logger.debug("processing %s", speakerFile)
            train, val, test = preprocessingCombined.getOneSpeaker(
                    speakerFile=speakerFile, sourceDataDir=sourceDataDir,
                    trainFraction=0.0, validFraction=0.0,
                    storeProcessed=storeProcessed, processedDir=processedDir, logger=logger)

            images_train, mfccs_train, audioLabels_train, validLabels_train, validAudioFrames_train = train
            images_val, mfccs_val, audioLabels_val, validLabels_val, validAudioFrames_val = val
            images_test, mfccs_test, audioLabels_test, validLabels_test, validAudioFrames_test = test

            if verbose:
                logger.debug("the number of training examples is: %s", len(images_train))
                logger.debug("the number of valid examples is:    %s", len(images_val))
                logger.debug("the number of test examples is:     %s", len(images_test))

            # get results for testidation  set
            test_cost_one, test_acc_one, test_topk_acc_one, test_batches_one = self.val_epoch(mfccs=mfccs_test,
                                                                                              validLabels=audioLabels_test,
                                                                                              valid_frames=validAudioFrames_test)
            test_acc += test_acc_one;
            test_cost += test_cost_one;
            test_topk_acc += test_topk_acc_one
            nb_test_batches += test_batches_one;

            if verbose:
                logger.debug("  this speaker results: ")
                logger.debug("\ttest cost:   %s", test_cost_one / test_batches_one)
                logger.debug("\vtest acc rate:  %s %%", test_acc_one / test_batches_one * 100)
                logger.debug("\vtest  top 3 acc rate:  %s %%", test_topk_acc_one / test_batches_one * 100)

        # get the average over all speakers
        test_cost /= nb_test_batches
        test_acc = test_acc / nb_test_batches * 100
        test_topk_acc = test_topk_acc / nb_test_batches * 100

        return test_cost, test_acc, test_topk_acc


    def train(self, dataset, database_binaryDir, storeProcessed=False, processedDir=None, save_name='Best_model',
              num_epochs=100, batch_size=1, LR_start=1e-4, LR_decay=1,
              shuffleEnabled=True, compute_confusion=False, debug=False, logger=logger_RNNtools):

        trainingSpeakerFiles, testSpeakerFiles = dataset

        logger.info("\n* Starting training...")

        # try to load performance metrics of stored model
        if os.path.exists(save_name + ".npz") and os.path.exists(save_name + "_trainInfo.pkl"):
            old_train_info = unpickle(save_name + '_trainInfo.pkl')
            # backward compatibility
            if type(old_train_info) == list:
                old_train_info = old_train_info[0]
                best_val_acc = min(old_train_info[2])
                test_cost = min(old_train_info[3])
                test_acc = min(old_train_info[3])
            elif type(old_train_info) == dict:  # normal case
                best_val_acc = min(old_train_info['val_acc'])
                test_cost = min(old_train_info['test_cost'])
                test_acc = min(old_train_info['test_acc'])
                try:
                    test_topk_acc = min(old_train_info['test_topk_acc'])
                except:
                    test_topk_acc = 0
            else:
                best_val_acc = 0
                test_topk_acc = 0
                test_cost = 0
                test_acc = 0
        else:
            best_val_acc = 0
            test_topk_acc = 0
            test_cost = 0
            test_acc = 0

        logger.info("Initial best Val acc: %s", best_val_acc)
        logger.info("Initial best test acc: %s\n", test_acc)

        # init some performance keepers
        best_epoch = 1
        LR = LR_start
        # for storage of training info
        self.network_train_info = {
            'train_cost': [],
            'val_cost':   [], 'val_acc': [], 'val_topk_acc': [],
            'test_cost':  [], 'test_acc': [], 'test_topk_acc': []
        }  # used to be list of lists
        self.epochsNotImproved = 0

        logger.info("starting training for %s epochs...", num_epochs)
        # now run through the epochs

        # # TODO: remove this
        test_cost, test_acc, test_topk_acc = self.evalTEST(testSpeakerFiles,
                                                      sourceDataDir=database_binaryDir,
                                                      storeProcessed=storeProcessed,
                                                      processedDir=processedDir)
        logger.info("TEST results: ")
        logger.info("\t  test cost:        %s", test_cost)
        logger.info("\t  test acc rate:  %s %%", test_acc)
        logger.info("\t  test top 3 acc:  %s %%", test_topk_acc)
        # # TODO: end remove


        for epoch in range(num_epochs):
            logger.info("\n\n\n Epoch %s started", epoch + 1)
            start_time = time.time()

            train_cost, val_cost, val_acc, val_topk_acc = self.evalTRAINING(trainingSpeakerFiles, LR, shuffleEnabled,
                                                                            sourceDataDir=database_binaryDir,
                                                                            storeProcessed=storeProcessed,
                                                                            processedDir=processedDir)

            # test if validation acc went up
            printTest = False
            if val_acc > best_val_acc:
                printTest = True
                best_val_acc = val_acc
                best_epoch = epoch + 1

                logger.info("\n\nBest ever validation score; evaluating TEST set...")

                test_cost, test_acc, test_topk_acc = self.evalTEST(testSpeakerFiles,
                                                                   sourceDataDir=database_binaryDir,
                                                                   storeProcessed=storeProcessed,
                                                                   processedDir=processedDir)
                logger.info("TEST results: ")
                logger.info("\t  test cost:        %s", test_cost)
                logger.info("\t  test acc rate:  %s %%", test_acc)
                logger.info("\t  test top 3 acc:  %s %%", test_topk_acc)

                self.best_cost = val_cost
                self.best_epoch = self.curr_epoch
                self.best_param = L.get_all_param_values(self.network_lout)
                logger.info("New best model found!")
                if save_name is not None:
                    logger.info("Model saved as " + save_name)
                    self.save_model(save_name)

            epoch_duration = time.time() - start_time

            # Then we logger.info the results for this epoch:
            logger.info("Epoch %s of %s took %s seconds", epoch + 1, num_epochs, epoch_duration)
            logger.info("  LR:                            %s", LR)
            logger.info("  training cost:                 %s", train_cost)
            logger.info("  validation cost:               %s", val_cost)
            logger.info("  validation acc rate:         %s %%", val_acc)
            logger.info("  validation top 3 acc rate:         %s %%", val_topk_acc)
            logger.info("  best epoch:                    %s", best_epoch)
            logger.info("  best validation acc rate:    %s %%", best_val_acc)
            if printTest:
                logger.info("  test cost:                 %s", test_cost)
                logger.info("  test acc rate:           %s %%", test_acc)
                logger.info("  test top 3 acc rate:    %s %%", test_topk_acc)

            # save the training info
            self.network_train_info['train_cost'].append(train_cost)
            self.network_train_info['val_cost'].append(val_cost)
            self.network_train_info['val_acc'].append(val_acc)
            self.network_train_info['val_topk_acc'].append(val_topk_acc)
            self.network_train_info['test_cost'].append(test_cost)
            self.network_train_info['test_acc'].append(test_acc)
            self.network_train_info['test_topk_acc'].append(test_topk_acc)

            store_path = save_name + '_trainInfo.pkl'
            saveToPkl(store_path, self.network_train_info)
            logger.info("Train info written to:\t %s", store_path)

            # decay the LR
            # LR *= LR_decay
            LR = self.updateLR(LR, LR_decay)

            if self.epochsNotImproved > 5:
                logger.warning("\n\n NO MORE IMPROVEMENTS -> stop training")
                test_cost, test_acc, test_topk_acc = self.evalTEST(testSpeakerFiles,
                                                                   sourceDataDir=database_binaryDir,
                                                                   storeProcessed=storeProcessed,
                                                                   processedDir=processedDir)
                logger.info("FINAL TEST results: ")
                logger.info("\t  test cost:        %s", test_cost)
                logger.info("\t  test acc rate:  %s %%", test_acc)
                logger.info("\t  test top 3 acc:  %s %%", test_topk_acc)
                break

        logger.info("Done.")

    def updateLR(self, LR, LR_decay, logger=logger_RNNtools):
        this_cost = self.network_train_info['val_cost'][-1]
        try:
            last_cost = self.network_train_info['val_cost'][-2]
        except:
            last_cost = 10 * this_cost  # first time it will fail because there is only 1 result stored

        # only reduce LR if not much improvment anymore
        if this_cost / float(last_cost) >= 0.98:
            logger.info(" Error not much reduced: %s vs %s. Reducing LR: %s", this_cost, last_cost, LR * LR_decay)
            self.epochsNotImproved += 1
            return LR * LR_decay
        else:
            self.epochsNotImproved = max(self.epochsNotImproved - 1, 0)  # reduce by 1, minimum 0
            return LR