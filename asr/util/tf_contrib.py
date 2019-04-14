"""Utility and helper methods for TensorFlow speech learning."""

import tensorflow as tf

from asr.params import FLAGS, TF_FLOAT


class AdamOptimizerLogger(tf.train.AdamOptimizer):
    """Modified `AdamOptimizer`_ that logs it's learning rate and step.

    .. _AdamOptimizer:
        https://www.tensorflow.org/api_docs/python/tf/train/AdamOptimizer
    """

    def _apply_dense(self, grad, var):
        m = self.get_slot(var, 'm')
        v = self.get_slot(var, 'v')
        beta1_power, beta2_power = self._get_beta_accumulators()

        m_hat = m / (1.0 - beta1_power)
        v_hat = v / (1.0 - beta2_power)

        step = m_hat / (v_hat ** 0.5 + self._epsilon_t)

        # Use a histogram summary to monitor it during training.
        tf.summary.histogram('step', step)

        current_lr = self._lr_t * tf.sqrt(1.0 - beta2_power) / (1.0 - beta1_power)
        tf.summary.scalar('estimated_lr', current_lr)

        return super(AdamOptimizerLogger, self)._apply_dense(grad, var)


def dense_layers(sequences, training, regularizer, initializer,
                 num_layers=3, activation=tf.nn.relu):
    """Create a chain of dense (fully-connected) neural network layers.

    Args:
        sequences (tf.Tensor): Input sequences.
        training (bool): Whether the mode is training or not.
        regularizer: TF weight reqularizer.
        initializer: TF weight initializer.
        num_layers (int):
        activation (function): TF activation function.

    Returns:
        tf.Tensor: Output tensor.
    """

    with tf.variable_scope('dense'):
        output = sequences
        for _ in range(num_layers):
            output = tf.layers.dense(output, FLAGS.num_units_dense,
                                     activation=activation,
                                     kernel_initializer=initializer,
                                     kernel_regularizer=regularizer)
            output = tf.minimum(output, FLAGS.relu_cutoff)
            output = tf.layers.dropout(output, rate=FLAGS.dense_dropout_rate, training=training)
            # output = [batch_size, time, num_units_dense]

        return output


def conv_layers(sequences,
                filters=FLAGS.conv_filters,
                kernel_sizes=((11, 41), (11, 21), (11, 21)),
                strides=((2, 2), (1, 2), (1, 2)),
                kernel_initializer=tf.glorot_normal_initializer(),
                kernel_regularizer=None,
                training=True):
    """Add 2D convolutional layers to the network's graph. New sequence length are being calculated.

    Convolutional layer output shapes:
    Conv 'VALID' output width (W) is calculated by:
        W = (W_i - K_w) // S_w + 1
    Conv 'SAME' output width (W) is calculated by:
        W = (W_i - K_w + 2*(K_w//2)) // S_w + 1
    Where W_i is the input width, K_w the kernel width, and S_w the stride width.
    Height (H) is calculated analog to width (W).

    For the default setup, the convolutional layers reduce `output` size to:
        conv1 = [batch_size, W, H, NUM_CHANNELS] = [batch_size, ~time / 2, 40, NUM_FILTERS]
        conv2 = [batch_size, W, H, NUM_CHANNELS] = [batch_size, ~time, 20, NUM_FILTERS]
        conv3 = [batch_size, W, H, NUM_CHANNELS] = [batch_size, ~time, 10, NUM_FILTERS]

    This values are reshaped to input for a following RNN layer by the following metric:
        [batch_size, time, 10 * NUM_FILTERS]
    where 10 is the number of frequencies left over from convolutions.

    Args:
        sequences (tf.Tensor):
            The input sequences.
        filters (Tuple[int]):
            Tuple of number of filters per convolutional layers.
        kernel_sizes (Tuple[Tuple[int, int]]):
            Tuple of tuples of height and width values. One tuple per convolutional layer.
        strides (Tuple[Tuple[int, int]]):
            Tuple of tuples of x and y stride values. One tuple per convolutional layer.
        kernel_initializer (tf.Tensor):
            TensorFlow kernel initializer.
        kernel_regularizer (tf.Tensor):
            TensorFlow kernel regularizer.
        training (bool):
            `FLAGS.conv_dropout_rate` is being applied during training only.

    Returns:
        tf.Tensor: `output`
            Convolutional layers output.
        tf.Tensor: `seq_length`
            Sequence length of the batch elements. Note that the shortest samples within a
            batch are stretched to the convolutional length of the longest one.

    .. _`conv2d`:
        https://www.tensorflow.org/api_docs/python/tf/layers/conv2d
    """

    if not (len(filters) == len(kernel_sizes) == len(strides)):
        raise ValueError('conv_layers(): Arguments filters, kernel_size, and strides must contain '
                         'the same number of elements.')

    output = sequences
    for tmp in zip(filters, kernel_sizes, strides):
        _filter, kernel_size, stride = tmp

        output = tf.layers.conv2d(inputs=output,
                                  filters=_filter,
                                  kernel_size=kernel_size,
                                  strides=stride,
                                  padding='SAME',
                                  activation=tf.nn.relu,
                                  kernel_initializer=kernel_initializer,
                                  kernel_regularizer=kernel_regularizer)

        output = tf.minimum(output, FLAGS.relu_cutoff)
        output = tf.layers.dropout(output, rate=FLAGS.conv_dropout_rate, training=training)

    # Reshape to: conv3 = [batch_size, time, 10 * NUM_FILTERS], where 10 is the number of
    # frequencies left over from convolutions.
    output = tf.reshape(output, [tf.shape(output)[0], -1, 10 * filters[-1]])

    # Update seq_length to convolutions. shape[1] = time steps; shape[0] = batch_size
    # Note that the shortest samples within a batch are stretched to the convolutional
    # length of the longest one.
    seq_length = tf.tile([tf.shape(output)[1]], [tf.shape(output)[0]])

    return output, seq_length


def bidirectional_cells(num_units, num_layers, dropout=1.0):
    """Create two lists of forward and backward cells that can be used to build a BDLSTM stack.

    Args:
        num_units (int): Number of units within the RNN cell.
        num_layers (int): Amount of cells to create for each list.
        dropout (float): Probability [0, 1] to drop an output. If it's constant 0
            no outputs will be dropped.

    Returns:
        [tf.nn.rnn_cell.LSTMCell]: List of forward cells.
        [tf.nn.rnn_cell.LSTMCell]: List of backward cells.
    """
    keep_prob = min(1.0, max(0.0, 1.0 - dropout))

    _fw_cells = [create_cell(num_units, keep_prob=keep_prob) for _ in range(num_layers)]
    _bw_cells = [create_cell(num_units, keep_prob=keep_prob) for _ in range(num_layers)]
    return _fw_cells, _bw_cells


def create_cell(num_units, keep_prob=1.0):
    """Create a RNN cell with added dropout wrapper.

    Args:
        num_units (int): Number of units within the RNN cell.
        keep_prob (float): Probability [0, 1] to keep an output. It it's constant 1
            no outputs will be dropped.

    Returns:
        tf.nn.rnn_cell.LSTMCell: RNN cell with dropout wrapper.
    """
    # Can be: `tf.nn.rnn_cell.RNNCell`, `tf.nn.rnn_cell.GRUCell`, `tf.nn.rnn_cell.LSTMCell`.

    # https://www.tensorflow.org/api_docs/python/tf/contrib/rnn/LSTMCell
    # cell = tf.nn.rnn_cell.LSTMCell(num_units=num_units, use_peepholes=True)

    # https://www.tensorflow.org/api_docs/python/tf/contrib/rnn/GRUCell
    # cell = tf.nn.rnn_cell.GRUCell(num_units=num_units)

    # https://www.tensorflow.org/api_docs/python/tf/contrib/rnn/BasicRNNCell
    cell = tf.nn.rnn_cell.BasicRNNCell(num_units=num_units, activation=tf.nn.tanh)

    return tf.nn.rnn_cell.DropoutWrapper(cell,
                                         input_keep_prob=keep_prob,
                                         output_keep_prob=keep_prob,
                                         seed=FLAGS.random_seed)


def variable_on_cpu(name, shape, initializer):
    """Helper to create a variable stored on CPU memory.

    Args:
        name (str): Name of the variable.
        shape (list of int): List of ints, e.g. a numpy shape.
        initializer: Initializer for the variable.

    Returns:
        tf.Tensor: Variable tensor.
    """
    with tf.device('/cpu:0'):
        return tf.get_variable(name, shape, initializer=initializer, dtype=TF_FLOAT)


def variable_with_weight_decay(name, shape, stddev, weight_decay):
    """Helper to create an initialized variable with weight decay.

    Note that the variable is initialized with a truncated normal distribution.
    A weight decay is added only if one is specified.

    Args:
        name (str): Name of the variable.
        shape (list of int): List of ints, e.g. a numpy shape.
        stddev (float): Standard deviation of the Gaussian.
        weight_decay: Add L2Loss weight decay multiplied by this float.
            If None, weight decay is not added for this variable.

    Returns:
        tf.Tensor: Variable tensor.
    """
    initializer = tf.truncated_normal_initializer(stddev=stddev, dtype=TF_FLOAT)
    var = variable_on_cpu(name, shape, initializer=initializer)

    if weight_decay is not None:
        weight_decay = tf.multiply(tf.nn.l2_loss(var), weight_decay, name='weight_loss')
        tf.add_to_collection('losses', weight_decay)

    return var
