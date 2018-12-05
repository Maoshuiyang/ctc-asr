"""
Transcribe a given audio file.

L8ER: Add flag to specify the checkpoint file to use.
"""

import os

import tensorflow as tf

from python.dataset.config import CSV_DIR
from python.input_functions import load_sample
from python.model import CTCModel
from python.params import FLAGS, get_parameters
from python.util import storage

# Inference specific flags.
tf.flags.DEFINE_string('input',
                       os.path.join(CSV_DIR, 'examples/idontunderstandawordyoujustsaid.wav'),
                       "Path to the WAV file to transcribe.")


def predict_input_fn():
    """
    Generate a `tf.data.Dataset` containing the `FLAGS.input` file's spectrogram data.

    Returns:
        Dataset iterator.
    """
    dataset = tf.data.Dataset.from_generator(__predict_input_generator,
                                             (tf.float32, tf.int32),
                                             (tf.TensorShape([None, 80]), tf.TensorShape([]))
                                             )

    dataset = dataset.batch(1)
    iterator = dataset.make_one_shot_iterator()
    spectrogram, spectrogram_length = iterator.get_next()

    features = {
        'spectrogram': spectrogram,
        'spectrogram_length': spectrogram_length,
    }

    return features, None


def __predict_input_generator():
    yield load_sample(FLAGS.input)


def main(_):
    """TensorFlow evaluation starting routine."""

    # Delete old model data if requested.
    storage.maybe_delete_checkpoints(FLAGS.train_dir, FLAGS.delete)

    # Logging information about the run.
    print('TensorFlow-Version: {}; Tag-Version: {}; Branch: {}; Commit: {}\nParameters: {}'
          .format(tf.VERSION, storage.git_latest_tag(), storage.git_branch(),
                  storage.git_revision_hash(), get_parameters()))

    # Setup TensorFlow run configuration and hooks.
    config = tf.estimator.RunConfig(
        model_dir=FLAGS.train_dir,
        save_summary_steps=FLAGS.log_frequency,
        session_config=tf.ConfigProto(
            log_device_placement=FLAGS.log_device_placement,
            gpu_options=tf.GPUOptions(allow_growth=FLAGS.allow_vram_growth)
        ),
        keep_checkpoint_max=5,
        log_step_count_steps=FLAGS.log_frequency,
        train_distribute=None
    )

    model = CTCModel()

    # Construct the estimator that embodies the model.
    estimator = tf.estimator.Estimator(
        model_fn=model.model_fn,
        model_dir=FLAGS.train_dir,
        config=config
    )

    # Evaluate the given example.
    prediction = estimator.predict(input_fn=predict_input_fn, hooks=None)
    tf.logging.info('Inference results: {}'.format(list(prediction)))


if __name__ == '__main__':
    # General TensorFlow setup.
    tf.enable_eager_execution()
    tf.logging.set_verbosity(tf.logging.INFO)

    # Run training.
    tf.app.run()
