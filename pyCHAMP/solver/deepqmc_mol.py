import numpy as np 
import torch
from torch.autograd import Variable, grad
from torch import nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
from functools import partial
from pyCHAMP.solver.solver_base import SOLVER_BASE

from pyCHAMP.solver.torch_utils import QMCDataSet, QMCLoss

import matplotlib.pyplot as plt

from tqdm import tqdm
import time


class DeepQMC(SOLVER_BASE):

    def __init__(self, wf=None, sampler=None, optimizer=None):

        SOLVER_BASE.__init__(self,wf,sampler,None)
        self.opt = optimizer
        self.batchsize = 100


    def sample(self,ntherm=10):

        t0 = time.time()
        pos = self.sampler.generate(self.wf.pdf,ntherm=ntherm)
        pos = torch.tensor(pos)
        pos = pos.view(-1,self.sampler.ndim*self.sampler.nelec)
        pos.requires_grad = True
        return pos.float()

    def observalbe(self,func,pos):
        obs = []
        for p in tqdm(pos):
            obs.append( func(p).data.numpy().tolist() )
        return obs

    def train(self,nepoch,pos=None,ntherm=0):

        if pos is None:
            pos = self.sample(ntherm=ntherm)

        dataset = QMC_DataSet(pos)
        dataloader = DataLoader(dataset,batch_size=self.batchsize)
        qmc_loss = QMCLoss(self.wf,method='variance')
        
        cumulative_loss = []
        for n in range(nepoch):
            print('\n === epoch %d' %n)

            cumulative_loss.append(0) 
            for data in dataloader:
                
                print("\n data ", data.shape)

                data = Variable(data).float()
                data.requires_grad = True
                t0 = time.time()
                out = self.wf(data)
                print("\t WF done in %f" %(time.time()-t0))

                t0 = time.time()
                loss = qmc_loss(data)
                cumulative_loss[n] += loss
                print("\t Loss (%f) done in %f" %(loss,time.time()-t0))
                self.wf = self.wf.train()

                self.opt.zero_grad()

                t0 = time.time()
                loss.backward()
                print("\t Backward done in %f" %(time.time()-t0))

                t0 = time.time()
                self.opt.step()
                print("\t opt done in %f" %(time.time()-t0))

                q,r = torch.qr(self.wf.layer_mo.weight.transpose(0,1))
                self.wf.layer_mo.weight.data = q.transpose(0,1)
                print(self.wf.layer_mo.weight)
                print(self.wf.layer_ci.weight)

            print('=== epoch %d loss %f \n' %(n,cumulative_loss[n]))

            if 1:
                pos = self.sample(ntherm=ntherm)
                dataloader.dataset.data = pos

        plt.plot(cumulative_loss)
        plt.show()