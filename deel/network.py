import chainer.functions as F
import chainer.links as L
from chainer import Variable
from chainer.links import caffe
from chainer import computational_graph as c
from tensor import *
from network import *
from deel import *
import chainer
import json
import os
import multiprocessing
import threading
import time
import six
import numpy as np
import os.path
from PIL import Image
from six.moves import queue
import pickle
import cv2
import hashlib
import datetime
import sys
import random



class Network(object):
	t = None
	def __init__(self,name):
		self.name=name
		self.func=None
	def predict(self,x):
		'''
			Forward neural Network to prediction
		'''
		return None
	def classify(self,x=None):
		'''
			Classify x
		'''
		return None
	def trainer(self):
		'''
			Trainer for neural network
		'''
		return None
	def __str__(self):
		return self.name


def filter(image):
	cropwidth = 256 - ImageNet.in_size
	start = cropwidth // 2
	stop = start + ImageNet.in_size
	mean_image = ImageNet.mean_image[:, start:stop, start:stop].copy()
	target_shape = (256, 256)
	output_side_length=256

	height, width, depth = image.shape
	new_height = output_side_length
	new_width = output_side_length
	if height > width:
		new_height = output_side_length * height / width
	else:
		new_width = output_side_length * width / height
	resized_img = cv2.resize(image, (new_width, new_height))
	height_offset = (new_height - output_side_length) / 2
	width_offset = (new_width - output_side_length) / 2
	image= resized_img[height_offset:height_offset + output_side_length,
	width_offset:width_offset + output_side_length]

	image = image.transpose(2, 0, 1)
	image = image[:, start:stop, start:stop].astype(np.float32)
	image -= mean_image

	return image

'''
	ImageNet
'''
class ImageNet(Network):
	mean_image=None
	in_size=224
	mean_image=None
	def __init__(self,name,in_size=224):
		super(ImageNet,self).__init__(name)
		ImageNet.in_size = in_size
	def Input(self,x):
		if isinstance(x,str):
			img = Image.open(x)
			t = ImageTensor(img,filtered_image=filter(np.asarray(img)),
							in_size=self.in_size)
		elif hasattr(x,'_Image__transformer'):
			t = ImageTensor(x,filtered_image=filter(np.asarray(x)),
							in_size=self.in_size)
		else:
			t = ImageTensor(x,filtered_image=filter(np.asarray(x)),
							in_size=self.in_size)
		t.use()
		return t

__Model_cache={}

def LoadCaffeModel(path):
	print "Loading %s"%path
	root, ext = os.path.splitext(path)
	cashnpath = 'cash/'+hashlib.sha224(root).hexdigest()+".pkl"
	if path in __Model_cache:
		print "Cache hit"
		func = __Model_cache[path]
	if os.path.exists(cashnpath):
		func = pickle.load(open(cashnpath,'rb'))
	else:
		print "Converting from %s"%path
		func = caffe.CaffeFunction('misc/'+path)
		pickle.dump(func, open(cashnpath, 'wb'))
	__Model_cache[path]=func
	return func
	

'''
	GoogLeNet by Caffenet 
'''
class GoogLeNet(ImageNet):
	def __init__(self,modelpath='bvlc_googlenet.caffemodel',
					mean='ilsvrc_2012_mean.npy',
					labels='labels.txt',in_size=224):
		super(GoogLeNet,self).__init__('GoogLeNet',in_size)

		self.func = LoadCaffeModel(modelpath)

		ImageNet.mean_image = np.ndarray((3, 256, 256), dtype=np.float32)
		ImageNet.mean_image[0] = 104
		ImageNet.mean_image[1] = 117
		ImageNet.mean_image[2] = 123
		ImageNet.in_size = in_size

		self.labels = np.loadtxt("misc/"+labels, str, delimiter="\t")

	def forward(self,x):
		y, = self.func(inputs={'data': x}, outputs=['loss3/classifier'],
					disable=['loss1/ave_pool', 'loss2/ave_pool'],
					train=False)
		return F.softmax(y)

	def classify(self,x=None):
		if x is None:
			x=Tensor.context

		_x = Variable(x.value, volatile=True)
		result = self.forward(_x)
		result = Variable(result.data) #Unchain 
		t = ChainerTensor(result)
		t.owner=self
		t.use()

		return t

'''
	Network in Network by Chainer 
'''
import model.nin

class NetworkInNetwork(ImageNet):
	def __init__(self,mean='data/mean.npy',labels='data/labels.txt',optimizer=None):
		super(NetworkInNetwork,self).__init__('NetworkInNetwork',in_size=227)

		self.func = model.nin.NIN()
		self.graph_generated=None

		ImageNet.mean_image = pickle.load(open(mean, 'rb'))
		ImageNet.in_size = self.func.insize

		self.labels = np.loadtxt(labels, str, delimiter="\t")

		self.t = ChainerTensor(Variable(Deel.xp.asarray([1.0])))

		if Deel.gpu>=0:
			self.func.to_gpu()

		Deel.optimizer_lr=0.01

		if optimizer is None:
			self.optimizer = optimizers.MomentumSGD(Deel.optimizer_lr, momentum=0.9)
		self.optimizer.setup(self.func)


	def forward(self,x):
		y = self.func.forward(x)
		return y

	def classify(self,x=None):
		if x is None:
			x=Tensor.context

		_x = x.content
		result = self.forward(_x)
		self.t.content=result
		self.t.owner=self
		self.t.use()
		
		return self.t


	def backprop(self,t):
		x=Tensor.context


		self.optimizer.lr = Deel.optimizer_lr

		self.optimizer.zero_grads()
		loss,accuracy = self.func.getLoss(x.content,t.content)

		loss.backward()
		self.optimizer.update()
		

		if not self.graph_generated:
			#with open('graph.dot', 'w') as o:
			#	o.write(c.build_computational_graph((loss,), False).dump())
			with open('graph.wo_split.dot', 'w') as o:
				o.write(c.build_computational_graph((loss,), True).dump())
			print('generated graph')
			self.graph_generated = True


		return loss.data,accuracy.data


class AlexNet(ImageNet):
	def __init__(self, model='bvlc_alexnet.caffemodel',mean='data/ilsvrc_2012_mean.npy',labels='data/labels.txt',optimizer=None):
		super(AlexNet,self).__init__('AlexNet',in_size=227)


		self.func = LoadCaffeModel(model)
		self.labels = np.loadtxt(labels, str, delimiter="\t")

		if Deel.gpu >= 0:
			cuda.check_cuda_available()


		if Deel.gpu >= 0:
			cuda.get_device(self.gpu).use()
			self.func.to_gpu()

		#ImageNet.mean_image = np.load(mean)
		mean_image = np.load(mean)
		ImageNet.mean_image=mean_image
		
		cropwidth = 256 - self.in_size
		start = cropwidth // 2
		stop = start + self.in_size
		self.mean_image = mean_image[:, start:stop, start:stop].copy()
		#del self.func.layers[15:23] 
		#self.outname = 'pool5'

		self.batchsize = 1
		self.x_batch = np.ndarray((self.batchsize, 3, self.in_size, self.in_size), dtype=np.float32)

	def forward(self, x,layer='fc8'):
		y, = self.func(inputs={'data': x}, outputs=[layer], train=False)
		return y
				
	def predict(self, x,layer='fc8'):
		y, = self.func(inputs={'data': x}, outputs=[layer], train=False)
		return F.softmax(y)


	def classify(self,x=None):
		if x is None:
			x=Tensor.context

		if not isinstance(x,ImageTensor):
			x=self.Input(x)

		_x = Variable(x.value, volatile=True)
		result = self.forward(_x)
		result = Variable(result.data) #Unchain 
		t = ChainerTensor(result)
		t.owner=self
		t.use()

		return t


	def feature(self, x):
		if x is None:
			x=Tensor.context
		if not isinstance(x,ImageTensor):
			x=self.Input(x)

		image = x.value
		'''
		camera_image = x.value

		cropwidth = 256 - self.in_size
		start = cropwidth // 2
		stop = start + self.in_size
		#x_batch = np.ndarray((self.batchsize, 3, self.in_size, self.in_size), dtype=np.float32)

		#image = np.asarray(camera_image).transpose(2, 0, 1)[::-1]
		image = camera_image[:, start:stop, start:stop].astype(np.float32)
		image -= self.mean_image

		'''

		self.x_batch[0] = image
		xp = Deel.xp
		x_data = xp.asarray(self.x_batch)

		if Deel.gpu >= 0:
			x_data=cuda.to_gpu(x_data)
		
		x = chainer.Variable(x_data, volatile=True)
		score = self.predict(x,layer='pool5')

		if Deel.gpu >= 0:
			score=cuda.to_cpu(score.data)
			score = score.reshape(256*6*6)
		else:
			score = score.data.reshape(256*6*6)
		print type(score)
		#print score.data.shape

		score = chainer.Variable(score, volatile=True)

		t = ChainerTensor(score)
		t.owner=self
		t.use()


		return t

	 
import copy
from rlglue.types import Action
from agentServer import AgentServer
import model.q_net
class DQN(Network):
	lastAction = Action()
	policyFrozen = False
	dim = 256 * 6 * 6
	epsilonDelta = 1.0 / 10 ** 4
	min_eps = 0.05

	def __init__(self):		
		super(DQN,self).__init__('Deep Q-learning Network')
		self.func = model.q_net.QNet(Deel.gpu)
		self.lastAction = Action()

		self.time = 0
		self.epsilon = 1.0  # Initial exploratoin rate

	def actionAndLearn(self,x=None):
		if x is None:
			x=Tensor.context

		if AgentServer.mode == 'start':
			return self.start(x)
		elif AgentServer.mode == 'step':
			return self.step(x)
		elif AgentServer.mode == 'end':
			return self.end(x)

	 
	def start(self,x=None):
		if x is None:
			x=Tensor.context

		obs_array = x.content.data
		
		# Initialize State
		self.state = np.zeros((self.func.hist_size, self.dim), dtype=np.uint8)
		self.state[0] = obs_array
		state_ = np.asanyarray(self.state.reshape(1, self.func.hist_size, self.dim), dtype=np.float32)
		if Deel.gpu >= 0:
			state_ = cuda.to_gpu(state_)

		# Generate an Action e-greedy
		returnAction = Action()
		action, Q_now = self.func.e_greedy(state_, self.epsilon)
		returnAction.intArray = [action]

		# Update for next step
		self.lastAction = copy.deepcopy(returnAction)
		self.last_state = self.state.copy()
		self.last_observation = obs_array

		return returnAction

	def step(self,x=None):
		if x is None:
			x=Tensor.context

		obs_array = x.content.data
		obs_processed = np.maximum(obs_array, self.last_observation)  # Take maximum from two frames

		# Compose State : 4-step sequential observation
		if self.func.hist_size == 4:
			self.state = np.asanyarray([self.state[1], self.state[2], self.state[3], obs_processed], dtype=np.uint8)
		elif self.func.hist_size == 1:
			self.state = np.asanyarray([obs_processed], dtype=np.uint8)
		else:
			print("self.DQN.hist_size err")

		state_ = np.asanyarray(self.state.reshape(1, self.func.hist_size, self.dim), dtype=np.float32)
		if Deel.gpu >= 0:
			state_ = cuda.to_gpu(state_)

		# Exploration decays along the time sequence
		if self.policyFrozen is False:  # Learning ON/OFF
			if self.func.initial_exploration < self.time:
				self.epsilon -= self.epsilonDelta
				if self.epsilon < self.min_eps:
					self.epsilon = self.min_eps
				eps = self.epsilon
			else:  # Initial Exploation Phase
				print "Initial Exploration : %d/%d steps" % (self.time, self.func.initial_exploration)
				eps = 1.0
		else:  # Evaluation
			print "Policy is Frozen"
			eps = 0.05

		# Generate an Action by e-greedy action selection
		returnAction = Action()
		action, Q_now = self.func.e_greedy(state_, eps)
		returnAction.intArray = [action]

		#return returnAction, action, eps, Q_now, obs_array, returnAction

		reward = AgentServer.reward

		'''
		Step after
		'''
		# Learning Phase
		if self.policyFrozen is False:  # Learning ON/OFF
			self.func.stock_experience(self.time, self.last_state, self.lastAction.intArray[0], reward, self.state, False)
			self.func.experience_replay(self.time)

		# Target model update
		if self.func.initial_exploration < self.time and np.mod(self.time, self.func.target_model_update_freq) == 0:
			print "########### MODEL UPDATED ######################"
			self.func.target_model_update()

		# Simple text based visualization
		if Deel.gpu >= 0:
			print 'Step %d/ACT %d/R %.1f/EPS %.6f/Q_max %3f' % (
				self.time, self.func.action_to_index(action), reward, eps, np.max(Q_now.get()))
		else:
			print 'Step %d/ACT %d/R %.1f/EPS %.6f/Q_max %3f' % (
				self.time, self.func.action_to_index(action), reward, eps, np.max(Q_now))

		# Updates for next step
		self.last_observation = obs_array

		if self.policyFrozen is False:
			self.lastAction = copy.deepcopy(returnAction)
			self.last_state = self.state.copy()
			self.time += 1
		return returnAction

	def dead(self,reward):
		print 'episode finished: REWARD %.1f / EPSILON %.5f' % (reward, self.epsilon)

		# Learning Phase
		if self.policyFrozen is False:  # Learning ON/OFF
			self.func.stock_experience(self.time, self.last_state, self.lastAction.intArray[0], reward, self.last_state,
										True)
			self.func.experience_replay(self.time)

		# Target model update
		if self.func.initial_exploration < self.time and np.mod(self.time, self.func.target_model_update_freq) == 0:
			print "########### MODEL UPDATED ######################"
			self.func.target_model_update()

		# Time count
		if self.policyFrozen is False:
			self.time += 1		
		





import model.lstm
class LSTM(Network):
	def __init__(self,optimizer=None,vocab=None,n_input_units=1000,
					n_units=650,grad_clip=5,bproplen=35):

		if vocab is None:
			vocab=BatchTrainer.vocab
		self.vocab=vocab
		n_vocab = len(vocab)
		super(LSTM,self).__init__('LSTM')

		self.func = model.lstm.RNNLM(n_input_units=n_input_units,n_vocab=n_vocab,n_units=n_units)
		self.func.compute_accuracy = False 
		for param in self.func.params():
			data = param.data
			data[:] = np.random.uniform(-0.1, 0.1, data.shape)


		if Deel.gpu>=0:
			self.func.to_gpu()


		if optimizer is None:
			self.optimizer = optimizers.SGD(lr=1.)
		self.optimizer.setup(self.func)
		self.clip = chainer.optimizer.GradientClipping(grad_clip)
		self.optimizer.add_hook(self.clip)

		self.accum_loss = 0
		self.cur_log_perp =  Deel.xp.zeros(())

	def evaluate(dataset):
		# Evaluation routine
		evaluator = self.func.copy()  # to use different state
		evaluator.predictor.reset_state()  # initialize state
		evaluator.predictor.train = False  # dropout does nothing

		sum_log_perp = 0
		for i in six.moves.range(dataset.size - 1):
			x = chainer.Variable(Deel.xp.asarray(dataset[i:i + 1]), volatile='on')
			t = chainer.Variable(Deel.xp.asarray(dataset[i + 1:i + 2]), volatile='on')
			loss = evaluator(x, t)
			sum_log_perp += loss.data
		return math.exp(float(sum_log_perp) / (dataset.size - 1))

	def forward(self,x=None):
		return self.func(x)

	def learn(self,str,x=None):
		if x is None:
			x=Tensor.context

		_t = Deel.xp.asarray([self.vocab[str[0]]], dtype=np.int32)
		t = ChainerTensor(Variable(_t))
		self.firstInput(t)

		
		for j in range(len(str)-2):
			_x = Deel.xp.asarray([self.vocab[str[j+1]]], dtype=np.int32)
			x = ChainerTensor(Variable(_x))
			x.use()

			_t = Deel.xp.asarray([self.vocab[str[j+2]]], dtype=np.int32)
			t = ChainerTensor(Variable(_t))
			self.train(t)
		

		return self.accum_loss.data



	def firstInput(self,t,x=None):
		if x is None:
			x=Tensor.context
		_x = x.content
		_t = t.content
		_y = self.func(_x,mode=1)
		loss = chainer.functions.loss.softmax_cross_entropy.softmax_cross_entropy(_y,_t)
		self.func.y = _y
		self.func.loss = loss
		self.accum_loss += loss
		self.cur_log_perp += loss.data

		return x

	def train(self,t,x=None):
		if x is None:
			x=Tensor.context
		_x = x.content
		_t = t.content

		_y = self.func(_x)
		loss= F.softmax_cross_entropy(_y,_t)
		self.func.y = _y
		self.func.loss = loss
		self.accum_loss += loss
		self.cur_log_perp += loss.data

		return self


	def backprop(self):
		self.func.zerograds()
		self.accum_loss.backward()
		self.accum_loss.unchain_backward()  # truncate
		self.accum_loss = 0
		self.optimizer.update()
		
import collections
def _sum_sqnorm(arr):
	sq_sum = collections.defaultdict(float)
	for x in arr:
		with cuda.get_device(x) as dev:
			x = x.ravel()
			s = x.dot(x)
			sq_sum[int(dev)] += s
	return sum([float(i) for i in six.itervalues(sq_sum)])
