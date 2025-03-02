# ResNet-50 network from the paper:
# "Deep Residual Learning for Image Recognition"
# http://arxiv.org/pdf/1512.03385v1.pdf
# License: see https://github.com/KaimingHe/deep-residual-networks/blob/master/LICENSE

# Download pretrained weights from:
# https://s3.amazonaws.com/lasagne/recipes/pretrained/imagenet/resnet50.pkl

from lasagne.layers import BatchNormLayer, Conv2DLayer as ConvLayer, DenseLayer, ElemwiseSumLayer, NonlinearityLayer
from lasagne.nonlinearities import rectify, softmax
import lasagne

def build_simple_block(incoming_layer, names,
                       num_filters, filter_size, stride, pad,
                       use_bias=False, nonlin=rectify):
    """Creates stacked Lasagne layers ConvLayer -> BN -> (ReLu)

    Parameters:
    ----------
    incoming_layer : instance of Lasagne layer
        Parent layer

    names : list of string
        Names of the layers in block

    num_filters : int
        Number of filters in convolution layer

    filter_size : int
        Size of filters in convolution layer

    stride : int
        Stride of convolution layer

    pad : int
        Padding of convolution layer

    use_bias : bool
        Whether to use bias in conlovution layer

    nonlin : function
        Nonlinearity type of Nonlinearity layer

    Returns
    -------
    tuple: (net, last_layer_name)
        net : dict
            Dictionary with stacked layers
        last_layer_name : string
            Last layer name
    """
    net = []
    net.append((
        names[0],
        ConvLayer(incoming_layer, num_filters, filter_size, pad, stride,
                  flip_filters=False, nonlinearity=None) if use_bias
        else ConvLayer(incoming_layer, num_filters, filter_size, stride, pad, b=None,
                       flip_filters=False, nonlinearity=None)
    ))

    net.append((
        names[1],
        BatchNormLayer(net[-1][1])
    ))
    if nonlin is not None:
        net.append((
            names[2],
            NonlinearityLayer(net[-1][1], nonlinearity=nonlin)
        ))

    return dict(net), net[-1][0]


def build_residual_block(incoming_layer, ratio_n_filter=1.0, ratio_size=1.0, has_left_branch=False,
                         upscale_factor=4, ix=''):
    """Creates two-branch residual block

    Parameters:
    ----------
    incoming_layer : instance of Lasagne layer
        Parent layer

    ratio_n_filter : float
        Scale factor of filter bank at the input of residual block

    ratio_size : float
        Scale factor of filter size

    has_left_branch : bool
        if True, then left branch contains simple block

    upscale_factor : float
        Scale factor of filter bank at the output of residual block

    ix : int
        Id of residual block

    Returns
    -------
    tuple: (net, last_layer_name)
        net : dict
            Dictionary with stacked layers
        last_layer_name : string
            Last layer name
    """
    simple_block_name_pattern = ['res%s_branch%i%s', 'bn%s_branch%i%s', 'res%s_branch%i%s_relu']

    net = {}

    # right branch
    net_tmp, last_layer_name = build_simple_block(
            incoming_layer, map(lambda s: s % (ix, 2, 'a'), simple_block_name_pattern),
            int(lasagne.layers.get_output_shape(incoming_layer)[1] * ratio_n_filter), 1, int(1.0 / ratio_size), 0)
    net.update(net_tmp)

    net_tmp, last_layer_name = build_simple_block(
            net[last_layer_name], map(lambda s: s % (ix, 2, 'b'), simple_block_name_pattern),
            lasagne.layers.get_output_shape(net[last_layer_name])[1], 3, 1, 1)
    net.update(net_tmp)

    net_tmp, last_layer_name = build_simple_block(
            net[last_layer_name], map(lambda s: s % (ix, 2, 'c'), simple_block_name_pattern),
            lasagne.layers.get_output_shape(net[last_layer_name])[1] * upscale_factor, 1, 1, 0,
            nonlin=None)
    net.update(net_tmp)

    right_tail = net[last_layer_name]
    left_tail = incoming_layer

    # left branch
    if has_left_branch:
        net_tmp, last_layer_name = build_simple_block(
                incoming_layer, map(lambda s: s % (ix, 1, ''), simple_block_name_pattern),
                int(lasagne.layers.get_output_shape(incoming_layer)[1] * 4 * ratio_n_filter), 1, int(1.0 / ratio_size),
                0,
                nonlin=None)
        net.update(net_tmp)
        left_tail = net[last_layer_name]

    net['res%s' % ix] = ElemwiseSumLayer([left_tail, right_tail], coeffs=1)
    net['res%s_relu' % ix] = NonlinearityLayer(net['res%s' % ix], nonlinearity=rectify)

    return net, 'res%s_relu' % ix


def build_network_resnet50(input, nbClasses):
    net = {}
    net['input'] = InputLayer(shape=(None, 1, 120, 120), input_var=input)
    sub_net, parent_layer_name = build_simple_block(
            net['input'], ['conv1', 'bn_conv1', 'conv1_relu'],
            64, 7, 3, 2, use_bias=True)
    net.update(sub_net)
    net['pool1'] = PoolLayer(net[parent_layer_name], pool_size=3, stride=2, pad=0, mode='max', ignore_border=False)
    block_size = list('abc')
    parent_layer_name = 'pool1'
    for c in block_size:
        if c == 'a':
            sub_net, parent_layer_name = build_residual_block(net[parent_layer_name], 1, 1, True, 4, ix='2%s' % c)
        else:
            sub_net, parent_layer_name = build_residual_block(net[parent_layer_name], 1.0 / 4, 1, False, 4,
                                                              ix='2%s' % c)
        net.update(sub_net)

    block_size = list('abcd')
    for c in block_size:
        if c == 'a':
            sub_net, parent_layer_name = build_residual_block(
                    net[parent_layer_name], 1.0 / 2, 1.0 / 2, True, 4, ix='3%s' % c)
        else:
            sub_net, parent_layer_name = build_residual_block(net[parent_layer_name], 1.0 / 4, 1, False, 4,
                                                              ix='3%s' % c)
        net.update(sub_net)

    block_size = list('abcdef')
    for c in block_size:
        if c == 'a':
            sub_net, parent_layer_name = build_residual_block(
                    net[parent_layer_name], 1.0 / 2, 1.0 / 2, True, 4, ix='4%s' % c)
        else:
            sub_net, parent_layer_name = build_residual_block(net[parent_layer_name], 1.0 / 4, 1, False, 4,
                                                              ix='4%s' % c)
        net.update(sub_net)

    #import pdb;pdb.set_trace()
    print("Parameters before abc: ", lasagne.layers.count_params(net[parent_layer_name]))
    block_size = list('abc')
    for c in block_size:
        if c == 'a':
            sub_net, parent_layer_name = build_residual_block(
                    net[parent_layer_name], 1.0 / 2, 1.0 / 2, True, 4, ix='5%s' % c)
        else:
            sub_net, parent_layer_name = build_residual_block(net[parent_layer_name], 1.0 / 4, 1, False, 4,
                                                              ix='5%s' % c)
        net.update(sub_net)

    print("Parameters before pool5: ", lasagne.layers.count_params(net[parent_layer_name]))

    net['pool5'] = PoolLayer(net[parent_layer_name], pool_size=7, stride=1, pad=0,
                             mode='average_exc_pad', ignore_border=False)

    print("Parameters before FC: ", lasagne.layers.count_params(net['pool5']))

    net['fc1000'] = DenseLayer(net['pool5'], num_units=nbClasses,
                               nonlinearity=None)  # number output units = nbClasses (global variable)
    net['prob'] = NonlinearityLayer(net['fc1000'], nonlinearity=softmax)

    return net, net['prob']


# network from Oxford & Google BBC paper
def build_network_google(activation, alpha, epsilon, input, nbClasses):
    # input
    # store each layer of the network in a dict, for quickly retrieving any layer
    cnnDict = {}
    cnnDict['l0_in'] = lasagne.layers.InputLayer(
            shape=(None, 1, 120, 120),  # 5,120,120 (5 = #frames)
            input_var=input)

    cnnDict['l1_conv1'] = []
    cnnDict['l1_conv1'].append(lasagne.layers.Conv2DLayer(
            cnnDict['l0_in'],
            num_filters=128,
            filter_size=(3, 3),
            pad=1,
            nonlinearity=lasagne.nonlinearities.identity))
    cnnDict['l1_conv1'].append(lasagne.layers.MaxPool2DLayer(cnnDict['l1_conv1'][-1], pool_size=(2, 2)))
    cnnDict['l1_conv1'].append(lasagne.layers.BatchNormLayer(
            cnnDict['l1_conv1'][-1],
            epsilon=epsilon,
            alpha=alpha))
    cnnDict['l1_conv1'].append(lasagne.layers.NonlinearityLayer(
            cnnDict['l1_conv1'][-1],
            nonlinearity=activation))

    # conv 2
    cnnDict['l2_conv2'] = []
    cnnDict['l2_conv2'].append(lasagne.layers.Conv2DLayer(
            cnnDict['l1_conv1'][-1],
            num_filters=256,
            filter_size=(3, 3),
            stride=(2, 2),
            pad=1,
            nonlinearity=lasagne.nonlinearities.identity))
    cnnDict['l2_conv2'].append(lasagne.layers.MaxPool2DLayer(cnnDict['l2_conv2'][-1], pool_size=(2, 2)))
    cnnDict['l2_conv2'].append(lasagne.layers.BatchNormLayer(
            cnnDict['l2_conv2'][-1],
            epsilon=epsilon,
            alpha=alpha))
    cnnDict['l2_conv2'].append(lasagne.layers.NonlinearityLayer(
            cnnDict['l2_conv2'][-1],
            nonlinearity=activation))

    # conv3
    cnnDict['l3_conv3'] = []
    cnnDict['l3_conv3'].append(lasagne.layers.Conv2DLayer(
            cnnDict['l2_conv2'][-1],
            num_filters=512,
            filter_size=(3, 3),
            pad=1,
            nonlinearity=lasagne.nonlinearities.identity))
    cnnDict['l3_conv3'].append(lasagne.layers.NonlinearityLayer(
            cnnDict['l3_conv3'][-1],
            nonlinearity=activation))

    # conv 4
    cnnDict['l4_conv4'] = []
    cnnDict['l4_conv4'].append(lasagne.layers.Conv2DLayer(
            cnnDict['l3_conv3'][-1],
            num_filters=512,
            filter_size=(3, 3),
            pad=1,
            nonlinearity=lasagne.nonlinearities.identity))
    cnnDict['l4_conv4'].append(lasagne.layers.NonlinearityLayer(
            cnnDict['l4_conv4'][-1],
            nonlinearity=activation))

    # conv 5
    cnnDict['l5_conv5'] = []
    cnnDict['l5_conv5'].append(lasagne.layers.Conv2DLayer(
            cnnDict['l4_conv4'][-1],
            num_filters=512,
            filter_size=(3, 3),
            pad=1,
            nonlinearity=lasagne.nonlinearities.identity))
    cnnDict['l5_conv5'].append(lasagne.layers.MaxPool2DLayer(
            cnnDict['l5_conv5'][-1],
            pool_size=(2, 2)))
    cnnDict['l5_conv5'].append(lasagne.layers.NonlinearityLayer(
            cnnDict['l5_conv5'][-1],
            nonlinearity=activation))

    # disable this layer for normal phoneme recognition
    # FC layer
    # cnnDict['l6_fc'] = []
    # cnnDict['l6_fc'].append(lasagne.layers.DenseLayer(
    #         cnnDict['l5_conv5'][-1],
    #        nonlinearity=lasagne.nonlinearities.identity,
    #        num_units=256))
    #
    # cnnDict['l6_fc'].append(lasagne.layers.NonlinearityLayer(
    #         cnnDict['l6_fc'][-1],
    #         nonlinearity=activation))


    # output layer
    cnnDict['l7_out'] = lasagne.layers.DenseLayer(
            # cnnDict['l6_fc'][-1],
            cnnDict['l5_conv5'][-1],
            nonlinearity=lasagne.nonlinearities.softmax,
            num_units=nbClasses)

    # cnn = lasagne.layers.BatchNormLayer(
    #       cnn,
    #       epsilon=epsilon,
    #       alpha=alpha)

    return cnnDict, cnnDict['l7_out']


def build_network_cifar10(activation, alpha, epsilon, input, nbClasses):
    cnn = lasagne.layers.InputLayer(
            shape=(None, 1, 120, 120),
            input_var=input)

    # 128C3-128C3-P2
    cnn = lasagne.layers.Conv2DLayer(
            cnn,
            num_filters=128,
            filter_size=(3, 3),
            pad=1,
            nonlinearity=lasagne.nonlinearities.identity)

    cnn = lasagne.layers.BatchNormLayer(
            cnn,
            epsilon=epsilon,
            alpha=alpha)

    cnn = lasagne.layers.NonlinearityLayer(
            cnn,
            nonlinearity=activation)

    cnn = lasagne.layers.Conv2DLayer(
            cnn,
            num_filters=128,
            filter_size=(3, 3),
            pad=1,
            nonlinearity=lasagne.nonlinearities.identity)

    cnn = lasagne.layers.MaxPool2DLayer(cnn, pool_size=(2, 2))

    cnn = lasagne.layers.BatchNormLayer(
            cnn,
            epsilon=epsilon,
            alpha=alpha)

    cnn = lasagne.layers.NonlinearityLayer(
            cnn,
            nonlinearity=activation)

    # 256C3-256C3-P2
    cnn = lasagne.layers.Conv2DLayer(
            cnn,
            num_filters=256,
            filter_size=(3, 3),
            pad=1,
            nonlinearity=lasagne.nonlinearities.identity)

    cnn = lasagne.layers.BatchNormLayer(
            cnn,
            epsilon=epsilon,
            alpha=alpha)

    cnn = lasagne.layers.NonlinearityLayer(
            cnn,
            nonlinearity=activation)

    cnn = lasagne.layers.Conv2DLayer(
            cnn,
            num_filters=256,
            filter_size=(3, 3),
            pad=1,
            nonlinearity=lasagne.nonlinearities.identity)

    cnn = lasagne.layers.MaxPool2DLayer(cnn, pool_size=(2, 2))
    #
    cnn = lasagne.layers.BatchNormLayer(
            cnn,
            epsilon=epsilon,
            alpha=alpha)

    cnn = lasagne.layers.NonlinearityLayer(
            cnn,
            nonlinearity=activation)
    #
    # 512C3-512C3-P2
    cnn = lasagne.layers.Conv2DLayer(
            cnn,
            num_filters=512,
            filter_size=(3, 3),
            pad=1,
            nonlinearity=lasagne.nonlinearities.identity)

    cnn = lasagne.layers.BatchNormLayer(
            cnn,
            epsilon=epsilon,
            alpha=alpha)

    cnn = lasagne.layers.NonlinearityLayer(
            cnn,
            nonlinearity=activation)
    #
    cnn = lasagne.layers.Conv2DLayer(
            cnn,
            num_filters=512,
            filter_size=(3, 3),
            pad=1,
            nonlinearity=lasagne.nonlinearities.identity)

    cnn = lasagne.layers.MaxPool2DLayer(cnn, pool_size=(2, 2))

    cnn = lasagne.layers.BatchNormLayer(
            cnn,
            epsilon=epsilon,
            alpha=alpha)

    cnn = lasagne.layers.NonlinearityLayer(
            cnn,
            nonlinearity=activation)

    # print(cnn.output_shape)

    cnn = lasagne.layers.DenseLayer(
            cnn,
            nonlinearity=lasagne.nonlinearities.identity,
            num_units=256)
    #
    cnn = lasagne.layers.BatchNormLayer(
            cnn,
            epsilon=epsilon,
            alpha=alpha)

    cnn = lasagne.layers.NonlinearityLayer(
            cnn,
            nonlinearity=activation)

    cnn = lasagne.layers.DenseLayer(
            cnn,
            nonlinearity=lasagne.nonlinearities.softmax,
            num_units=nbClasses)

    # cnn = lasagne.layers.BatchNormLayer(
    #         cnn,
    #         epsilon=epsilon,
    #         alpha=alpha)

    return {}, cnn


# default network for cifar10

from lasagne.layers import InputLayer, DropoutLayer
from lasagne.layers.dnn import Conv2DDNNLayer as ConvLayer
from lasagne.layers import Pool2DLayer as PoolLayer


def build_network_cifar10_v2(input, nbClasses):
    net = {}
    net['input'] = InputLayer((None, 1, 120, 120), input_var=input)
    net['conv1'] = ConvLayer(net['input'],
                             num_filters=192,
                             filter_size=5,
                             pad=2,
                             flip_filters=False)
    net['cccp1'] = ConvLayer(
            net['conv1'], num_filters=160, filter_size=1, flip_filters=False)
    net['cccp2'] = ConvLayer(
            net['cccp1'], num_filters=96, filter_size=1, flip_filters=False)
    net['pool1'] = PoolLayer(net['cccp2'],
                             pool_size=3,
                             stride=2,
                             mode='max',
                             ignore_border=False)
    net['drop3'] = DropoutLayer(net['pool1'], p=0.5)
    net['conv2'] = ConvLayer(net['drop3'],
                             num_filters=192,
                             filter_size=5,
                             pad=2,
                             flip_filters=False)
    net['cccp3'] = ConvLayer(
            net['conv2'], num_filters=192, filter_size=1, flip_filters=False)
    net['cccp4'] = ConvLayer(
            net['cccp3'], num_filters=192, filter_size=1, flip_filters=False)
    net['pool2'] = PoolLayer(net['cccp4'],
                             pool_size=3,
                             stride=2,
                             mode='average_exc_pad',
                             ignore_border=False)
    net['drop6'] = DropoutLayer(net['pool2'], p=0.5)
    net['conv3'] = ConvLayer(net['drop6'],
                             num_filters=192,
                             filter_size=3,
                             pad=1,
                             flip_filters=False)
    net['cccp5'] = ConvLayer(
            net['conv3'], num_filters=192, filter_size=1, flip_filters=False)
    net['cccp6'] = ConvLayer(
            net['cccp5'], num_filters=10, filter_size=1, flip_filters=False)
    net['pool3'] = PoolLayer(net['cccp6'],
                             pool_size=8,
                             mode='average_exc_pad',
                             ignore_border=False)
    # net['output'] = FlattenLayer(net['pool3'])

    net['dense1'] = DenseLayer(
            net['pool3'],
            nonlinearity=lasagne.nonlinearities.identity,
            num_units=1024)

    net['output'] = lasagne.layers.DenseLayer(
            net['dense1'],
            nonlinearity=lasagne.nonlinearities.softmax,
            num_units=nbClasses)

    return net, net['output']

# ################## BINARY NETWORKS ###################
#
# import lasagne
#
# # Our own rounding function, that does not set the gradient to 0 like Theano's
# from code.lipreading.binary.old import binary_net
#
#
# def build_network_google_binary(activation, alpha, epsilon, input, binary, stochastic, H, W_LR_scale):
#     # input
#     cnn = lasagne.layers.InputLayer(
#             shape=(None, 1, 120, 120),  # 5,120,120 (5 = #frames)
#             input_var=input)
#
#     # conv 1
#     cnn = binary_net.Conv2DLayer(
#             cnn,
#             binary=binary,
#             stochastic=stochastic,
#             H=H,
#             W_LR_scale=W_LR_scale,
#             num_filters=128,
#             filter_size=(3, 3),
#             pad=1,
#             nonlinearity=lasagne.nonlinearities.identity)
#     cnn = lasagne.layers.MaxPool2DLayer(cnn, pool_size=(2, 2))
#     cnn = lasagne.layers.BatchNormLayer(
#             cnn,
#             epsilon=epsilon,
#             alpha=alpha)
#     cnn = lasagne.layers.NonlinearityLayer(
#             cnn,
#             nonlinearity=activation)
#
#     # conv 2
#     cnn = binary_net.Conv2DLayer(
#             cnn,
#             binary=binary,
#             stochastic=stochastic,
#             H=H,
#             W_LR_scale=W_LR_scale,
#             num_filters=256,
#             filter_size=(3, 3),
#             stride=(2, 2),
#             pad=1,
#             nonlinearity=lasagne.nonlinearities.identity)
#     cnn = lasagne.layers.MaxPool2DLayer(cnn, pool_size=(2, 2))
#     cnn = lasagne.layers.BatchNormLayer(
#             cnn,
#             epsilon=epsilon,
#             alpha=alpha)
#     cnn = lasagne.layers.NonlinearityLayer(
#             cnn,
#             nonlinearity=activation)
#
#     # conv3
#     cnn = binary_net.Conv2DLayer(
#             cnn,
#             binary=binary,
#             stochastic=stochastic,
#             H=H,
#             W_LR_scale=W_LR_scale,
#             num_filters=512,
#             filter_size=(3, 3),
#             pad=1,
#             nonlinearity=lasagne.nonlinearities.identity)
#     cnn = lasagne.layers.NonlinearityLayer(
#             cnn,
#             nonlinearity=activation)
#
#     # conv 4
#     cnn = binary_net.Conv2DLayer(
#             cnn,
#             binary=binary,
#             stochastic=stochastic,
#             H=H,
#             W_LR_scale=W_LR_scale,
#             num_filters=512,
#             filter_size=(3, 3),
#             pad=1,
#             nonlinearity=lasagne.nonlinearities.identity)
#     cnn = lasagne.layers.NonlinearityLayer(
#             cnn,
#             nonlinearity=activation)
#
#     # conv 5
#     cnn = binary_net.Conv2DLayer(
#             cnn,
#             binary=binary,
#             stochastic=stochastic,
#             H=H,
#             W_LR_scale=W_LR_scale,
#             num_filters=512,
#             filter_size=(3, 3),
#             pad=1,
#             nonlinearity=lasagne.nonlinearities.identity)
#     cnn = lasagne.layers.MaxPool2DLayer(cnn, pool_size=(2, 2))
#     cnn = lasagne.layers.NonlinearityLayer(
#             cnn,
#             nonlinearity=activation)
#
#     # FC layer
#     cnn = binary_net.DenseLayer(
#             cnn,
#             binary=binary,
#             stochastic=stochastic,
#             H=H,
#             W_LR_scale=W_LR_scale,
#             nonlinearity=lasagne.nonlinearities.identity,
#             num_units=39)
#
#     return cnn
#
#
# def build_network_cifar10_binary(activation, alpha, epsilon, input, binary, stochastic, H, W_LR_scale):
#     cnn = lasagne.layers.InputLayer(
#             shape=(None, 1, 120, 120),
#             input_var=input)
#
#     # 128C3-128C3-P2
#     cnn = binary_net.Conv2DLayer(
#             cnn,
#             binary=binary,
#             stochastic=stochastic,
#             H=H,
#             W_LR_scale=W_LR_scale,
#             num_filters=128,
#             filter_size=(3, 3),
#             pad=1,
#             nonlinearity=lasagne.nonlinearities.identity)
#
#     cnn = lasagne.layers.BatchNormLayer(
#             cnn,
#             epsilon=epsilon,
#             alpha=alpha)
#
#     cnn = lasagne.layers.NonlinearityLayer(
#             cnn,
#             nonlinearity=activation)
#
#     cnn = binary_net.Conv2DLayer(
#             cnn,
#             binary=binary,
#             stochastic=stochastic,
#             H=H,
#             W_LR_scale=W_LR_scale,
#             num_filters=128,
#             filter_size=(3, 3),
#             pad=1,
#             nonlinearity=lasagne.nonlinearities.identity)
#
#     cnn = lasagne.layers.MaxPool2DLayer(cnn, pool_size=(2, 2))
#
#     cnn = lasagne.layers.BatchNormLayer(
#             cnn,
#             epsilon=epsilon,
#             alpha=alpha)
#
#     cnn = lasagne.layers.NonlinearityLayer(
#             cnn,
#             nonlinearity=activation)
#
#     # 256C3-256C3-P2
#     cnn = binary_net.Conv2DLayer(
#             cnn,
#             binary=binary,
#             stochastic=stochastic,
#             H=H,
#             W_LR_scale=W_LR_scale,
#             num_filters=256,
#             filter_size=(3, 3),
#             pad=1,
#             nonlinearity=lasagne.nonlinearities.identity)
#
#     cnn = lasagne.layers.BatchNormLayer(
#             cnn,
#             epsilon=epsilon,
#             alpha=alpha)
#
#     cnn = lasagne.layers.NonlinearityLayer(
#             cnn,
#             nonlinearity=activation)
#
#     cnn = binary_net.Conv2DLayer(
#             cnn,
#             binary=binary,
#             stochastic=stochastic,
#             H=H,
#             W_LR_scale=W_LR_scale,
#             num_filters=256,
#             filter_size=(3, 3),
#             pad=1,
#             nonlinearity=lasagne.nonlinearities.identity)
#
#     cnn = lasagne.layers.MaxPool2DLayer(cnn, pool_size=(2, 2))
#
#     cnn = lasagne.layers.BatchNormLayer(
#             cnn,
#             epsilon=epsilon,
#             alpha=alpha)
#
#     cnn = lasagne.layers.NonlinearityLayer(
#             cnn,
#             nonlinearity=activation)
#
#     # 512C3-512C3-P2
#     cnn = binary_net.Conv2DLayer(
#             cnn,
#             binary=binary,
#             stochastic=stochastic,
#             H=H,
#             W_LR_scale=W_LR_scale,
#             num_filters=512,
#             filter_size=(3, 3),
#             pad=1,
#             nonlinearity=lasagne.nonlinearities.identity)
#
#     cnn = lasagne.layers.BatchNormLayer(
#             cnn,
#             epsilon=epsilon,
#             alpha=alpha)
#
#     cnn = lasagne.layers.NonlinearityLayer(
#             cnn,
#             nonlinearity=activation)
#
#     cnn = binary_net.Conv2DLayer(
#             cnn,
#             binary=binary,
#             stochastic=stochastic,
#             H=H,
#             W_LR_scale=W_LR_scale,
#             num_filters=512,
#             filter_size=(3, 3),
#             pad=1,
#             nonlinearity=lasagne.nonlinearities.identity)
#
#     cnn = lasagne.layers.MaxPool2DLayer(cnn, pool_size=(2, 2))
#
#     cnn = lasagne.layers.BatchNormLayer(
#             cnn,
#             epsilon=epsilon,
#             alpha=alpha)
#
#     cnn = lasagne.layers.NonlinearityLayer(
#             cnn,
#             nonlinearity=activation)
#
#     # print(cnn.output_shape)
#
#     # # 1024FP-1024FP-10FP
#     # cnn = binary_net.DenseLayer(
#     #         cnn,
#     #        binary=binary,
#     #       stochastic=stochastic,
#     #        H=H,
#     #       W_LR_scale=W_LR_scale,
#     #         nonlinearity=lasagne.nonlinearities.identity,
#     #         num_units=1024)
#     #
#     # cnn = lasagne.layers.BatchNormLayer(
#     #         cnn,
#     #         epsilon=epsilon,
#     #         alpha=alpha)
#     #
#     # cnn = lasagne.layers.NonlinearityLayer(
#     #         cnn,
#     #         nonlinearity=activation)
#
#     # cnn = binary_net.DenseLayer(
#     #        cnn,
#     #        binary=binary,
#     #        stochastic=stochastic,
#     #        H=H,
#     #        W_LR_scale=W_LR_scale,
#     #         nonlinearity=lasagne.nonlinearities.identity,
#     #         num_units=1024)
#     #
#     # cnn = lasagne.layers.BatchNormLayer(
#     #         cnn,
#     #         epsilon=epsilon,
#     #         alpha=alpha)
#     #
#     # cnn = lasagne.layers.NonlinearityLayer(
#     #         cnn,
#     #         nonlinearity=activation)
#
#     cnn = binary_net.DenseLayer(
#             cnn,
#             binary=binary,
#             stochastic=stochastic,
#             H=H,
#             W_LR_scale=W_LR_scale,
#             nonlinearity=lasagne.nonlinearities.identity,
#             num_units=39)
#
#     # cnn = lasagne.layers.BatchNormLayer(
#     #         cnn,
#     #         epsilon=epsilon,
#     #         alpha=alpha)
#
#     return cnn
