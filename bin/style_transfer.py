#!/usr/bin/python3
# Mohamed K. Eid (mohamedkeid@gmail.com)
# Description: TensorFlow implementation of "A Neural Algorithm of Artistic Style" using TV denoising as a regularizer.

import argparse
import custom_vgg19 as vgg19
import numpy as np
import os
import tensorflow as tf
import time
import utils
from functools import reduce

# Model Hyper Params
content_layer = 'conv4_2'
style_layers = ['conv1_1', 'conv2_1', 'conv3_1', 'conv4_1', 'conv5_1']
epochs = 300
learning_rate = .02
total_variation_smoothing = 1.5
norm_term = 6.
print_training_status = True

# Loss term weights
content_weight = 1.
style_weight = 3.
norm_weight = .1
tv_weight = .1

# Default image paths
dir_path = os.path.dirname(os.path.realpath(__file__))
input_path = dir_path + '/../lib/images/content/nyc.jpg'
style_path = dir_path + '/../lib/images/style/great-wave-of-kanagawa.jpg'
out_path = dir_path + '/../output/out_%.0f.jpg' % time.time()


# Given an activated filter maps of any particular layer, return its respected gram matrix
def convert_to_gram(filter_maps):
    # Get the dimensions of the filter maps to reshape them into two dimenions
    dimension = filter_maps.get_shape().as_list()
    reshaped_maps = tf.reshape(filter_maps, [dimension[1] * dimension[2], dimension[3]])

    # Compute the inner product to get the gram matrix
    if dimension[1] * dimension[2] > dimension[3]:
        return tf.matmul(reshaped_maps, reshaped_maps, transpose_a=True)
    else:
        return tf.matmul(reshaped_maps, reshaped_maps, transpose_b=True)


# Compute the content loss given a variable image (x) and a content image (c)
def get_content_loss(x, c):
    with tf.name_scope('get_content_loss'):
        # Get the activated VGG feature maps and return the normalized euclidean distance
        noise_representation = getattr(x, content_layer)
        photo_representation = getattr(c, content_layer)
        return get_l2_norm_loss(noise_representation - photo_representation)


# Compute the L2-norm divided by squared number of dimensions
def get_l2_norm_loss(diffs):
    shape = diffs.get_shape().as_list()
    size = reduce(lambda x, y: x * y, shape) ** 2
    sum_of_squared_diffs = tf.reduce_sum(tf.square(diffs))
    return sum_of_squared_diffs / size


# Compute style loss given a variable image (x) and a style image (s)
def get_style_loss(x, s):
    with tf.name_scope('get_style_loss'):
        style_layer_losses = [get_style_loss_for_layer(x, s, l) for l in style_layers]
        style_weights = tf.constant([1. / len(style_layer_losses)] * len(style_layer_losses), tf.float32)
        weighted_layer_losses = tf.mul(style_weights, tf.convert_to_tensor(style_layer_losses))
        return tf.reduce_sum(weighted_layer_losses)


# Compute style loss for a layer (l) given the variable image (x) and the style image (s)
def get_style_loss_for_layer(x, s, l):
    with tf.name_scope('get_style_loss_for_layer'):
        # Compute gram matrices using the activated filter maps of the art and generated images
        x_layer_maps = getattr(x, l)
        s_layer_maps = getattr(s, l)
        x_layer_gram = convert_to_gram(x_layer_maps)
        s_layer_gram = convert_to_gram(s_layer_maps)

        # Make sure the feature map dimensions are the same
        assert_equal_shapes = tf.assert_equal(x_layer_maps.get_shape(), s_layer_maps.get_shape())
        with tf.control_dependencies([assert_equal_shapes]):
            # Compute and return the normalized gram loss using the gram matrices
            shape = x_layer_maps.get_shape().as_list()
            size = reduce(lambda a, b: a * b, shape) ** 2
            gram_loss = get_l2_norm_loss(x_layer_gram - s_layer_gram)
            return gram_loss / size


# Compute total variation regularization loss term given a variable image (x) and its shape
def get_total_variation(x, shape):
    with tf.name_scope('get_total_variation'):
        # Get the dimensions of the variable image
        height = shape[1]
        width = shape[2]
        size = reduce(lambda a, b: a * b, shape) ** 2

        # Disjoin the variable image and evaluate the total variation
        x_cropped = x[:, :height - 1, :width - 1, :]
        left_term = tf.square(x[:, 1:, :width - 1, :] - x_cropped)
        right_term = tf.square(x[:, :height - 1, 1:, :] - x_cropped)
        smoothed_terms = tf.pow(left_term + right_term, total_variation_smoothing / 2.)
        return tf.reduce_sum(smoothed_terms) / size


# Parse arguments and assign them to their respective global variables
def parse_args():
    global input_path, style_path, out_path

    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=input_path, help="path to the input image you'd like to apply the style to")
    parser.add_argument("--style", default=style_path, help="path to the image you'd like to reference the style from")
    parser.add_argument("--out", default=out_path, help="path to where the styled image will be created")
    args = parser.parse_args()

    # Assign image paths from the arg parsing
    input_path = args.input
    style_path = args.style
    out_path = args.out


with tf.Session() as sess:
    parse_args()

    # Initialize and process photo image to be used for our content
    photo, image_shape = utils.load_image(input_path)
    image_shape = [1] + image_shape
    photo = photo.reshape(image_shape).astype(np.float32)

    # Initialize and process art image to be used for our style
    art = utils.load_image2(style_path, height=image_shape[1], width=image_shape[2])
    art = art.reshape(image_shape).astype(np.float32)

    # Initialize the variable image that will become our final output as random noise
    noise = tf.Variable(tf.truncated_normal(image_shape, mean=.5, stddev=.1))

    # VGG Networks Init
    with tf.name_scope('vgg_content'):
        content_model = vgg19.Vgg19()
        content_model.build(photo, image_shape[1:])

    with tf.name_scope('vgg_style'):
        style_model = vgg19.Vgg19()
        style_model.build(art, image_shape[1:])

    with tf.name_scope('vgg_x'):
        x_model = vgg19.Vgg19()
        x_model.build(noise, image_shape[1:])

    # Loss functions
    with tf.name_scope('loss'):
        # Content
        if content_weight is 0:
            content_loss = tf.constant(0.)
        else:
            content_loss = get_content_loss(x_model, content_model) * content_weight

        # Style
        if style_weight is 0:
            style_loss = tf.constant(0.)
        else:
            style_loss = get_style_loss(x_model, style_model) * style_weight

        # Norm regularization
        if norm_weight is 0:
            norm_loss = tf.constant(0.)
        else:
            norm_loss = (get_l2_norm_loss(noise) ** norm_term) * norm_weight

        # Total variation denoising
        if tv_weight is 0:
            tv_loss = tf.constant(0.)
        else:
            tv_loss = get_total_variation(noise, image_shape) * tv_weight

        # Total loss
        total_loss = content_loss + style_loss + norm_loss + tv_loss

    # Update image
    with tf.name_scope('update_image'):
        optimizer = tf.train.AdamOptimizer(learning_rate)
        grads = optimizer.compute_gradients(total_loss, [noise])
        clipped_grads = [(tf.clip_by_value(grad, -1., 1.), var) for grad, var in grads]
        update_image = optimizer.apply_gradients(clipped_grads)

    # Train
    print("Initializing variables and beginning training..")
    sess.run(tf.initialize_all_variables())
    start_time = time.time()
    for i in range(epochs):
        if print_training_status and i % 100 == 0:
            print("Epoch %04d | Loss %.03f" % (i, sess.run(total_loss)))
        sess.run(update_image)

    # FIN
    elapsed = time.time() - start_time
    print("Training complete. The session took %.2f seconds to complete." % elapsed)
    print("Rendering final image and closing TensorFlow session..")
    utils.render_img(sess, noise, save=True, out_path=out_path)
    sess.close()
