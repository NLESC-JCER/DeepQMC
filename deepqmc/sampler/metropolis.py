from deepqmc.sampler.sampler_base import SamplerBase
from tqdm import tqdm
import torch
from torch.autograd import Variable
from torch.distributions import MultivariateNormal
import numpy as np


class Metropolis(SamplerBase):

    def __init__(self, walkers, nstep=1000, step_size=3, transition='uniform'):
        """Metroplis Hasting sampler

        Args:
            walkers (walkers): a walker object
            nstep (int, optional): [description]. Defaults to 1000.
            step_size (int, optional): [description]. Defaults to 3.
        """

        SamplerBase.__init__(self, walkers, nstep, step_size)
        self.transition = transition

    def generate(self, pdf, ntherm=10, ndecor=100, pos=None,
                 with_tqdm=True):
        """Generate a series of point using MC sampling

        Args:
            pdf (callable): probability distribution function to be sampled
            ntherm (int, optional): number of step before thermalization.
                                    Defaults to 10.
            ndecor (int, optional): number of steps for decorrelation.
                                    Defaults to 50.
            pos (torch.tensor, optional): position to start with.
                                          Defaults to None.
            with_tqdm (bool, optional): tqdm progress bar. Defaults to True.

        Returns:
            torch.tensor: positions of the walkers
        """
        with torch.no_grad():

            if ntherm < 0:
                ntherm = self.nstep+ntherm

            self.walkers.initialize(pos=pos)

            fx = pdf(self.walkers.pos)
            fx[fx == 0] = 1E-16
            pos = []
            rate = 0
            idecor = 0

            if with_tqdm:
                rng = tqdm(range(self.nstep))
            else:
                rng = range(self.nstep)

            for istep in rng:

                # new positions
                Xn = self.move(pdf)

                # new function
                fxn = pdf(Xn)
                fxn[fxn == 0.] = 1E-16
                df = (fxn/(fx)).double()

                # accept the moves
                index = self._accept(df)

                # acceptance rate
                rate += index.byte().sum().float()/self.nwalkers

                # update position/function value
                self.walkers.pos[index, :] = Xn[index, :]
                fx[index] = fxn[index]
                fx[fx == 0] = 1E-16

                if (istep >= ntherm):
                    if (idecor % ndecor == 0):
                        pos.append(self.walkers.pos.clone().detach())
                    idecor += 1

            if with_tqdm:
                print("Acceptance rate %1.3f %%" % (rate/self.nstep*100))

        return torch.cat(pos)

    def move(self, pdf):
        """Move electron one at a time in a vectorized way.

        Args:
            step_size (float): size of the MC moves

        Returns:
            torch.tensor: new positions of the walkers
        """
        if self.nelec == 1:
            return self.walkers.pos + self._get_new_coord()

        else:
            # clone and reshape data : Nwlaker, Nelec, Ndim
            new_pos = self.walkers.pos.clone()
            new_pos = new_pos.view(self.nwalkers,
                                   self.nelec, self.ndim)

            # get indexes
            index = torch.LongTensor(self.nwalkers).random_(
                0, self.nelec)

            # change selected data
            if self.transition == 'uniform':
                new_pos[range(self.nwalkers), index,
                        :] += self._move_uniform()

            elif self.transition == 'drift':
                new_pos[range(self.nwalkers), index,
                        :] += self._move_drift(pdf, index)

            return new_pos.view(self.nwalkers, self.nelec*self.ndim)

    def _move_uniform(self):
        """Return a random array of length size between
        [-step_size,step_size]

        Args:
            step_size (float): boundary of the array
            size (int): number of points in the array

        Returns:
            torch.tensor: random array
        """

        return self.step_size * (2 * torch.rand((self.nwalkers, self.ndim)) - 1)

    def _move_drift(self, pdf, index):

        drift_val = 0.5 * \
            self._get_grad(pdf, self.walkers.pos) / \
            pdf(self.walkers.pos).view(-1, 1)
        drift_val = drift_val.view(self.nwalkers,
                                   self.nelec, self.ndim)

        mv = MultivariateNormal(torch.zeros(self.ndim), np.sqrt(
            self.step_size)*torch.eye(self.ndim))

        return self.step_size * drift_val[range(self.nwalkers), index, :] \
            + mv.sample((self.nwalkers, 1)).squeeze()

    @staticmethod
    def _get_grad(func, inp):
        '''Compute the gradient of a function
        wrt the value of its input

        Args:
            func : function to get the gradient of
            inp : input
        Returns:
            grad : gradient of the func wrt the input
        '''
        with torch.enable_grad():
            inp.requires_grad = True
            val = func(inp)
            z = Variable(torch.ones(val.shape))
            val.backward(z)
            fgrad = inp.grad.data
            inp.grad.data.zero_()
            inp.requires_grad = False
            return fgrad

    def _accept(self, P):
        """accept the move or not

        Args:
            P (torch.tensor): probability of each move

        Returns:
            t0rch.tensor: the indx of the accepted moves
        """
        P[P > 1] = 1.0
        tau = torch.rand(self.walkers.nwalkers).double()
        index = (P-tau >= 0).reshape(-1)
        return index.type(torch.bool)
