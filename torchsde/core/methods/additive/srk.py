# Copyright 2020 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Strong order 1.5 scheme for additive noise SDEs from

Rößler, Andreas. "Runge–Kutta methods for the strong approximation of solutions of stochastic differential
equations." SIAM Journal on Numerical Analysis 48, no. 3 (2010): 922-952.
"""
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import math

import torch

from torchsde.core import base_solver
from torchsde.core import misc
from torchsde.core.methods import utils
from torchsde.core.methods.tableaus import sra1

STAGES, C0, C1, A0, B0, alpha, beta1, beta2 = (
    sra1.STAGES, sra1.C0, sra1.C1, sra1.A0, sra1.B0, sra1.alpha, sra1.beta1, sra1.beta2
)


class SRKAdditive(base_solver.GenericSDESolver):

    def __init__(self, sde, bm, y0, dt, adaptive, rtol, atol, dt_min, options):
        super(SRKAdditive, self).__init__(
            sde=sde, bm=bm, y0=y0, dt=dt, adaptive=adaptive, rtol=rtol, atol=atol, dt_min=dt_min, options=options)
        # Trapezoidal approximation of \int_0^t W_s \ds using only `bm` allows for truly deterministic behavior.
        if 'trapezoidal_approx' in self.options and not self.options['trapezoidal_approx']:
            self.trapezoidal_approx = False
        else:
            self.trapezoidal_approx = True

    def step(self, t0, y0, dt):
        assert dt > 0, 'Underflow in dt {}'.format(dt)

        with torch.no_grad():
            sqrt_dt = torch.sqrt(dt) if isinstance(dt, torch.Tensor) else math.sqrt(dt)
            I_k = tuple((bm_next - bm_cur).to(y0[0]) for bm_next, bm_cur in zip(self.bm(t0 + dt), self.bm(t0)))
            I_k0 = (
                utils.compute_trapezoidal_approx(self.bm, t0, y0, dt, sqrt_dt) if self.trapezoidal_approx else
                tuple(dt / 2. * (delta_bm_ + torch.randn_like(delta_bm_) * sqrt_dt / math.sqrt(3)) for delta_bm_ in I_k)
            )

        t1, y1 = t0 + dt, y0
        H0 = []
        for i in range(STAGES):
            H0i = y0
            for j in range(i):
                f_eval = self.sde.f(t0 + C0[j] * dt, H0[j])
                g_eval = self.sde.g(t0 + C1[j] * dt, y0)  # The state should not affect the diffusion.

                H0i = tuple(
                    H0i_ + A0[i][j] * f_eval_ * dt + B0[i][j] * misc.batch_mvp(g_eval_, I_k0_) / dt
                    for H0i_, f_eval_, g_eval_, I_k0_ in zip(H0i, f_eval, g_eval, I_k0)
                )
                del f_eval, g_eval
            H0.append(H0i)

            f_eval = self.sde.f(t0 + C0[i] * dt, H0i)
            g_eval = self.sde.g(t0 + C1[i] * dt, y0)

            g_weight = tuple(
                beta1[i] * I_k_ + beta2[i] * I_k0_ / dt
                for I_k_, I_k0_ in zip(I_k, I_k0)
            )

            y1 = tuple(
                y1_ + alpha[i] * f_eval_ * dt + misc.batch_mvp(g_eval_, g_weight_)
                for y1_, f_eval_, g_eval_, g_weight_ in zip(y1, f_eval, g_eval, g_weight)
            )
        return t1, y1

    @property
    def strong_order(self):
        return 1.5
