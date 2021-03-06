from __future__ import print_function
import time
from multiprocessing import Process, Queue, Value

import numpy
from numpy import int16, uint16, uint8, float16, log2

import cv2
from cv2 import cvtColor as convertColor, COLOR_BGR2GRAY, COLOR_GRAY2RGB,\
                resize

try:                  #nearest neighboor interpolation
  from cv2.cv import CV_INTER_NN, \
                     CV_CAP_PROP_FRAME_WIDTH, \
                     CV_CAP_PROP_FRAME_HEIGHT, \
                     CV_CAP_PROP_FPS
except:
  from cv2 import INTER_NEAREST as CV_INTER_NN, \
                  CAP_PROP_FRAME_WIDTH as CV_CAP_PROP_FRAME_WIDTH, \
                  CAP_PROP_FRAME_HEIGHT as CV_CAP_PROP_FRAME_HEIGHT, \
                  CAP_PROP_FPS as CV_CAP_PROP_FPS

import pyximport; pyximport.install()
from pydvs.generate_spikes import *
from pydvs.virtual_cam import VirtualCam


MODE_128 = "128"
MODE_64  = "64"
MODE_32  = "32"
MODE_16  = "16"

UP_POLARITY     = "UP"
DOWN_POLARITY   = "DOWN"
MERGED_POLARITY = "MERGED"
RECTIFIED_POLARITY = "RECTIFIED"
POLARITY_DICT   = {UP_POLARITY: uint8(0),
                 DOWN_POLARITY: uint8(1),
                 MERGED_POLARITY: uint8(2),
                 RECTIFIED_POLARITY: uint8(3),
                 0: UP_POLARITY,
                 1: DOWN_POLARITY,
                 2: MERGED_POLARITY,
                 3: RECTIFIED_POLARITY}

OUTPUT_RATE         = "RATE"
OUTPUT_TIME         = "TIME"
OUTPUT_TIME_BIN     = "TIME_BIN"
OUTPUT_TIME_BIN_THR = "TIME_BIN_THR"

BEHAVE_MICROSACCADE = "SACCADE"
BEHAVE_ATTENTION    = "ATTENTION"
BEHAVE_TRAVERSE     = "TRAVERSE"
BEHAVE_FADE         = "FADE"

IMAGE_TYPES = ["png", 'jpeg', 'jpg']







# -------------------------------------------------------------------- #
# process image thread function                                        #

def processing_thread(img_queue, spike_queue, running):
  frame_count = 0
  #~ start_time = time.time()
  while True:
    img = img_queue.get()

    if img is None or running.value == 0:
      running.value = 0
      break

    # do the difference
    diff[:], abs_diff[:], spikes[:] = thresholded_difference(img, ref, threshold)
    # print("after thresholded_difference")

    # inhibition ( optional )
    if is_inh_on:
      spikes[:] = local_inhibition(spikes, abs_diff, inh_coords,
                                   width, height, inh_width)
    #   print("after inhibition")

    # update the reference
    ref[:] = update_reference_time_binary_thresh(abs_diff, spikes, ref,
                                                 threshold, max_time_ms,
                                                 num_active_bits,
                                                 history_weight,
                                                 log2_table)
    # print("after update_reference")

    # convert into a set of packages to send out
    neg_spks, pos_spks, max_diff = split_spikes(spikes, abs_diff, polarity)
    # print("after split_spikes")

    # this takes too long, could be parallelized at expense of memory
    spike_lists = make_spike_lists_time_bin_thr(pos_spks, neg_spks,
                                                max_diff,
                                                up_down_shift, data_shift, data_mask,
                                                max_time_ms,
                                                threshold,
                                                max_threshold,
                                                num_bits,
                                                log2_table)

    # print("after make_spike_lists")

    spike_queue.put(spike_lists)

    spk_img[:] = render_frame(spikes, img, cam_res, cam_res, polarity)
    # print("after render_frame")

    cv2.imshow ("spikes", spk_img.astype(uint8))
    if cv2.waitKey(1) & 0xFF == ord('q'):
      running.value = 0
      break


    #~ end_time = time.time()
#~
    #~ if end_time - start_time >= 1.0:
      #~ print("%d frames per second"%(frame_count))
      #~ frame_count = 0
      #~ start_time = time.time()
    #~ else:
      #~ frame_count += 1

  cv2.destroyAllWindows()
  running.value = 0


# -------------------------------------------------------------------- #
# send  image thread function                                          #

def emitting_thread(spike_queue, running):

  while True:
    spikes = spike_queue.get()

    if spikes is None or running.value == 0:
      running.value = 0
      break

    # Add favourite mechanisms to get spikes out of the pc
#    print("sending!")

  running.value = 0



#----------------------------------------------------------------------#
# global variables                                                     #

mode = MODE_64
cam_res = int(mode)
#cam_res = 256 <- can be done, but spynnaker doesn't suppor such resolution
width = cam_res # square output
height = cam_res
shape = (height, width)

data_shift = uint8( log2(cam_res) )
up_down_shift = uint8(2*data_shift)
data_mask = uint8(cam_res - 1)

polarity = POLARITY_DICT[ RECTIFIED_POLARITY ]
output_type = OUTPUT_TIME
history_weight = 1.0
threshold = 12 # ~ 0.05*255
max_threshold = 180 # 12*15 ~ 0.7*255

scale_width = 0
scale_height = 0
col_from = 0
col_to = 0

curr     = numpy.zeros(shape,     dtype=int16)
ref      = 128*numpy.ones(shape,  dtype=int16)
spikes   = numpy.zeros(shape,     dtype=int16)
diff     = numpy.zeros(shape,     dtype=int16)
abs_diff = numpy.zeros(shape,     dtype=int16)

# just to see things in a window
spk_img  = numpy.zeros((height, width, 3), uint8)

num_bits = 6   # how many bits are used to represent exceeded thresholds
num_active_bits = 2 # how many of bits are active
log2_table = generate_log2_table(num_active_bits, num_bits)[num_active_bits - 1]
spike_lists = None
pos_spks = None
neg_spks = None
max_diff = 0


# -------------------------------------------------------------------- #
# inhibition related                                                   #

inh_width = 2
is_inh_on = True
inh_coords = generate_inh_coords(width, height, inh_width)


# -------------------------------------------------------------------- #
# camera/frequency related                                             #

#video_dev = cv2.VideoCapture(0) # webcam
# video_dev = cv2.VideoCapture('./120fps HFR Sample.mp4') # webcam
fps = 90

behaviour = VirtualCam.BEHAVE_ATTENTION
video_dev = VirtualCam("./mnist/", fps=fps, resolution=cam_res, behaviour=behaviour)




#ps3 eyetoy can do 125fps
# try:
#   video_dev.set(CV_CAP_PROP_FRAME_WIDTH, 320)
#   video_dev.set(CV_CAP_PROP_FRAME_HEIGHT, 240)
#   video_dev.set(CV_CAP_PROP_FPS, 125)
# except:
#   pass

max_time_ms = int(1000./fps)


# -------------------------------------------------------------------- #
# threading related                                                    #

running = Value('i', 1)

spike_queue = Queue()
spike_emitting_proc = Process(target=emitting_thread,
                              args=(spike_queue, running))
spike_emitting_proc.start()

img_queue = Queue()
#~ spike_gen_proc = Process(target=self.process_frame, args=(img_queue,))
spike_gen_proc = Process(target=processing_thread,
                         args=(img_queue, spike_queue, running))
spike_gen_proc.start()


# -------------------------------------------------------------------- #
# main loop                                                            #

is_first_pass = True
start_time = time.time()
end_time = 0
frame_count = 0

while(running.value == 1):
  # get an image from video source0
  valid_img, curr[:] = video_dev.read(ref)

  img_queue.put(curr)


running.value == 0

img_queue.put(None)
spike_gen_proc.join()
print("generation thread stopped")

spike_queue.put(None)
spike_emitting_proc.join()
print("emission thread stopped")

if video_dev is not None:
  video_dev.release()
