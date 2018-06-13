#!/usr/bin/env python2
# -*- coding: utf-8 -*-
"""
Created on Tue Jun  5 15:15:21 2018

@author: eilers
"""

import numpy as np
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('TkAgg')
import scipy.optimize as op
import pickle
from astropy.table import Column, Table, join, vstack, hstack
from astropy.io import fits

# -------------------------------------------------------------------------------
# plotting settings
# -------------------------------------------------------------------------------

matplotlib.rcParams['ytick.labelsize'] = 14
matplotlib.rcParams['xtick.labelsize'] = 14
fsize = 14

# -------------------------------------------------------------------------------
# load spectra and labels
# -------------------------------------------------------------------------------

print('loading spectra...')
#f = open('data/all_spectra_norm_parent.pickle', 'rb')
#spectra = pickle.load(f)
#f.close()
hdu = fits.open('data/all_spectra_norm_parent.fits')
fluxes_orig = hdu[0].data

print('loading labels...')
hdu = fits.open('data/training_labels_parent.fits')
labels = Table(hdu[1].data)
 
# save all labels from the parent sample
labels_parent = 1. * labels

# -------------------------------------------------------------------------------
# load spectra and labels
# -------------------------------------------------------------------------------

# cross validation or infering parallaxes for complete parent sample?
validation = True

# make plots?
plots = False
                          
# -------------------------------------------------------------------------------
# add pixel mask to remove gaps between chips! 
# -------------------------------------------------------------------------------
               
gaps = (np.sum(fluxes_orig.T, axis = 0)) == float(fluxes_orig.T.shape[0])
fluxes = fluxes_orig[~gaps, :]

# -------------------------------------------------------------------------------
# add absolute Q magnitudes
# -------------------------------------------------------------------------------

print('calculating Q...')
m_K = labels['K']

Q_factor = 10**(0.2 * m_K) / 100.                 # assumes parallaxes is in mas
Q_K = labels['parallax'] * Q_factor
Q_K_err = labels['parallax_error'] * Q_factor

labels.add_column(Column(Q_K), name='Q_K')
labels.add_column(Column(Q_K_err), name='Q_K_ERR')

# -------------------------------------------------------------------------------
# also add WISE Q (not needed at the moment)
# -------------------------------------------------------------------------------

m_W1 = labels['w1mpro']
m_W2 = labels['w2mpro']
Q_W1 = 10**(0.2 * m_W1) * labels['parallax']/100.                    
Q_W2 = 10**(0.2 * m_W2) * labels['parallax']/100.                    
Q_W1_err = labels['parallax_error'] * 10**(0.2 * m_W1)/100.     
Q_W2_err = labels['parallax_error'] * 10**(0.2 * m_W2)/100.     
labels.add_column(Column(Q_W1), name='Q_W1')
labels.add_column(Column(Q_W2), name='Q_W2')
labels.add_column(Column(Q_W1_err), name='Q_W1_ERR')
labels.add_column(Column(Q_W2_err), name='Q_W2_ERR')

# -------------------------------------------------------------------------------
# create training and validation set
# -------------------------------------------------------------------------------

print('more quality cuts for training sample...')

# -------------------------------------------------------------------------------
# cuts in Q
# -------------------------------------------------------------------------------

cut = labels['Q_K'] < 0.5 # necessary?
labels = labels[cut]              
print('remove weird Q: {}'.format(len(labels)))
fluxes = fluxes[:, cut]
Q_factor = Q_factor[cut]

# -------------------------------------------------------------------------------
# visibility periods used
# -------------------------------------------------------------------------------

cut = labels['visibility_periods_used'] >= 8
labels = labels[cut]              
print('remove visibility periods < 8: {}'.format(len(labels)))
fluxes = fluxes[:, cut]
Q_factor = Q_factor[cut]

# -------------------------------------------------------------------------------
# cut in parallax_error
# -------------------------------------------------------------------------------

cut = labels['parallax_error'] < 0.1       # this cut is not strictly required!
labels = labels[cut]              
print('parallax error < 0.2: {0}'.format(len(labels)))
fluxes = fluxes[:, cut]   
Q_factor = Q_factor[cut]

# -------------------------------------------------------------------------------
# cut in b (only necessary if infering extinction from WISE colors doesn't work...)
# -------------------------------------------------------------------------------

bcut = 0
if bcut > 0:
    cut = np.abs(labels['b']) > bcut
    labels = labels[cut]              
    print('b > {0} cut: {1}'.format(bcut, len(labels)))
    fluxes = fluxes[:, cut]
    Q_factor = Q_factor[cut]

# -------------------------------------------------------------------------------
# more cuts?
# -------------------------------------------------------------------------------



# -------------------------------------------------------------------------------
# linear algebra
# -------------------------------------------------------------------------------

def H_func(x, y, A, lam, ivar):    
    H = 0.5 * np.dot((y - np.dot(A, x)).T, ivar * (y - np.dot(A, x))) + lam * np.sum(np.abs(x))
    dHdx = -1. * np.dot(A.T, ivar * (y - np.dot(A, x))) + lam * np.sign(x)
    return H, dHdx

def check_H_func(x, y, A, lam, ivar):
    H0, dHdx0 = H_func(x, y, A, lam, ivar)
    dx = 0.001 # magic
    for i in range(len(x)):
        x1 = 1. * x
        x1[i] += dx
        H1, foo = H_func(x1, y, A, lam, ivar)
        dHdx1 = (H1 - H0) / dx
        print(i, x[i], dHdx0[i], dHdx1, (dHdx1 - dHdx0[i]) / dHdx0[i])
    return

# -------------------------------------------------------------------------------
# cross validation
# -------------------------------------------------------------------------------

if validation:
    
    # data
    y_all = labels['Q_K'] 
    yerr_all = labels['Q_K_ERR'] 
    ivar_all = yerr_all ** (-2)
    
    JK = labels['J'] - labels['K']
    HW2 = labels['H'] - labels['w2mpro']
    JW1 = labels['J'] - labels['w1mpro']
    
    # design matrix
    AT_0 = np.vstack([np.ones_like(JK)])
    AT_linear = np.vstack([JK, labels['bp_rp'], JW1, HW2, fluxes])
    A_all = np.vstack([AT_0, AT_linear]).T
       
    # split into training and validation set
    Kfold = 2
    y_pred_all = np.zeros_like(y_all)
    lam = 100                       # hyperparameter -- needs to be tuned!
    
    name = 'N{0}_lam{1}_K{2}'.format(len(y_all), lam, Kfold)
    
    for k in range(Kfold):    
        
        valid = labels['random_index'] % Kfold == k
        train = np.logical_not(valid)
        y = y_all[train]
        ivar = ivar_all[train]
        A = A_all[train, :]
        N, M = A.shape
        x0 = np.zeros((M,))
                     
        # optimize H_func
        res = op.minimize(H_func, x0, args=(y, A, lam, ivar), method='L-BFGS-B', jac=True, options={'maxfun':50000}) 
        print(res)                       
                               
        # prediction
        y_pred = np.dot(A_all[valid, :], res.x) 
        y_pred_all[valid] = y_pred
                  
        dy = (y_all[valid] - y_pred_all[valid]) / y_all[valid]
        print('1 sigma: ', 0.5 * (np.percentile(dy, 84) - np.percentile(dy, 16)), 0.25 * (np.percentile(dy, 97.5) - np.percentile(dy, 2.5)))

        cut20 = labels['parallax'][valid]/labels['parallax_error'][valid] >= 20.
        dy20 = (y_all[valid][cut20] - y_pred_all[cut20]) / y_all[valid][cut20]
        print('1 sigma for best stars: ', 0.5 * (np.percentile(dy20, 84) - np.percentile(dy20, 16)), 0.25 * (np.percentile(dy20, 97.5) - np.percentile(dy20, 2.5)))

    
#    dy = (y_all[valid] - y_pred) / y_all[valid]
#    chi2 = np.median(ivar_all[valid] * (y_all[valid] - y_pred)**2)
#    print(0.5 * (np.percentile(dy, 84) - np.percentile(dy, 16)), 0.25 * (np.percentile(dy, 97.5) - np.percentile(dy, 2.5)))
#    
#    cut20 = np.where(training_labels['parallax'][valid]/training_labels['parallax_error'][valid] >= 20.)
#    dy20 = (y_all[valid][cut20] - y_pred[cut20]) / y_all[valid][cut20]
#    chi2_20 = np.median(ivar_all[valid][cut20] * (y_all[valid][cut20] - y_pred[cut20])**2)
#    print(0.5 * (np.percentile(dy20, 84) - np.percentile(dy20, 16)), 0.25 * (np.percentile(dy20, 97.5) - np.percentile(dy20, 2.5)))
#    
#    plt.scatter(y_all[valid][cut20], y_pred[cut20], c = ivar_all[valid][cut20], cmap = 'Spectral', alpha = .6)
#    plt.colorbar(label = r'$1/\sigma^2_Q$')
#    plt.plot((-10000, 10000), (-10000, 10000), lw = 1, color = colors[2])
#    plt.ylim(0, np.max(y))
#    plt.xlim(plt.ylim())
#    new_cut = np.where(y_pred[cut20] < 0.25)
#    dy_new = 0.5 * (np.percentile(dy20[new_cut], 84) - np.percentile(dy20[new_cut], 16))
#    plt.axhline(0.25, linestyle = '--', color = colors[2], label = r'$1\sigma = {}$'.format(round(dy_new, 3)), zorder = 0)
#    plt.xlabel(r'$Q_{K,\,\rm true}$', fontsize = 14)
#    plt.ylabel(r'$Q_{K,\,\rm pred}$', fontsize = 14)
#    plt.legend()
#    plt.title(r'$\varpi/\sigma_{{\varpi}} \geq 20: \lambda = {0}, 1\sigma = {1}$'.format(lam, round(0.5 * (np.percentile(dy20, 84) - np.percentile(dy20, 16)), 3)))
#    plt.savefig('plots/{0}/regularization_{1}.pdf'.format(date, name))
#    plt.close()
#    
#    cut10 = np.where(training_labels['parallax'][valid]/training_labels['parallax_error'][valid] >= 10.)
#    dy10 = (y_all[valid][cut10] - y_pred[cut10]) / y_all[valid][cut10]
#    chi2_10 = np.median(ivar_all[valid][cut10] * (y_all[valid][cut10] - y_pred[cut10])**2)
#    print(0.5 * (np.percentile(dy10, 84) - np.percentile(dy10, 16)), 0.25 * (np.percentile(dy10, 97.5) - np.percentile(dy10, 2.5)))
#    
#    plt.scatter(y_all[valid][cut10], y_pred[cut10], c = ivar_all[valid][cut10], cmap = 'Spectral', alpha = .6)
#    plt.colorbar(label = r'$1/\sigma^2_Q$')
#    plt.plot((-10000, 10000), (-10000, 10000), lw = 1, color = colors[2])
#    plt.ylim(0, np.max(y))
#    plt.xlim(plt.ylim())
#    plt.xlabel(r'$Q_{K,\,\rm true}$', fontsize = 14)
#    plt.ylabel(r'$Q_{K,\,\rm pred}$', fontsize = 14)
#    plt.title(r'$\varpi/\sigma_{{\varpi}} \geq 10: \lambda = {0}, 1\sigma = {1}$'.format(lam, round(0.5 * (np.percentile(dy10, 84) - np.percentile(dy10, 16)), 3)))
#    plt.savefig('plots/{0}/regularization10_{1}.pdf'.format(date, name))
#    plt.close()
#    
#    plt.plot(res.x)
#    plt.title(r'$\lambda = {}$'.format(lam))
#    plt.savefig('plots/{0}/regularization_results_{1}.pdf'.format(date, name))
#    plt.close()
#                           
        f = open('optimization/opt_results_{0}_{1}.pickle'.format(k, name), 'wb')
        pickle.dump(res, f)
        f.close()   

    spec_parallax = y_pred_all / Q_factor 
    labels.add_column(spec_parallax, name='spec_parallax')
    labels.add_column(y_pred_all, name='Q_pred')
    fits.writeto('data/training_labels_train_cv.fits'.format(name), labels)

# -------------------------------------------------------------------------------
# validation plots 
# -------------------------------------------------------------------------------

if plots:
    
    if validation:
        hdu = fits.open('data/training_labels_train_cv.fits')
        labels = hdu[1].data
    
    best = labels['parallax_over_error'] >= 20  
                 
    dy = (labels['parallax'] - labels['spec_parallax']) / labels['parallax']
    print('1 sigma inferred parallax: ', 0.5 * (np.percentile(dy, 84) - np.percentile(dy, 16)), 0.25 * (np.percentile(dy, 97.5) - np.percentile(dy, 2.5)))
    
    dy20 = (labels['parallax'][best] - labels['spec_parallax'][best]) / labels['parallax'][best]
    print('1 sigma  inferred parallax for best stars: ', 0.5 * (np.percentile(dy20, 84) - np.percentile(dy20, 16)), 0.25 * (np.percentile(dy20, 97.5) - np.percentile(dy20, 2.5)))

    fig, ax = plt.subplots(1, 2, figsize = (10, 5))
    ax[0].scatter(labels['parallax'], labels['spec_parallax'], c = labels['visibility_periods_used'], cmap = 'viridis_r', s = 10, vmin = 8, vmax = 20)
    plt.colorbar(label = 'visibility periods used')
    ax[0].set_title('all stars', fontsize = fsize)
    ax[0].set_title(r'$\varpi/\sigma_{\varpi} \geq 20$', fontsize = fsize)
    ax[1].scatter(labels['parallax'][best], labels['spec_parallax'][best], c = labels['visibility_periods_used'][best], cmap = 'viridis_r', s = 10, vmin = 8, vmax = 20)
    ax[0].plot([-100, 100], [-100, 100], linestyle = '--', color = 'k')
    ax[1].plot([-100, 100], [-100, 100], linestyle = '--', color = 'k')
    ax[0].set_ylim(0, 2)
    ax[0].set_xlim(0, 2)
    ax[1].set_ylim(0, 2)
    ax[1].set_xlim(0, 2)
    ax[0].set_xlabel('Gaia parallax', fontsize = fsize)
    ax[1].set_xlabel('Gaia parallax', fontsize = fsize)
    ax[0].set_ylabel('inferred parallax', fontsize = fsize)
    plt.savefig('plots/validation_parallax_inferred_{0}.pdf'.format(name))
    plt.close()
    
    fig, ax = plt.subplots(1, 2, figsize = (10, 5))
    ax[0].scatter(labels['parallax'], labels['spec_parallax'], c = labels['visibility_periods_used'], cmap = 'viridis_r', s = 10, vmin = 8, vmax = 20)
    plt.colorbar(label = 'visibility periods used')
    ax[0].set_title('all stars', fontsize = fsize)
    ax[0].set_title(r'$\varpi/\sigma_{\varpi} \geq 20$', fontsize = fsize)
    ax[1].scatter(labels['parallax'][best], labels['spec_parallax'][best], c = labels['visibility_periods_used'][best], cmap = 'viridis_r', s = 10, vmin = 8, vmax = 20)
    ax[0].plot([1e-5, 100], [1e-5, 100], 'k-')
    ax[1].plot([1e-5, 100], [1e-5, 100], 'k-')
    ax[0].set_ylim(1e-4, 5)
    ax[0].set_xlim(1e-4, 5)
    ax[1].set_ylim(1e-4, 5)
    ax[1].set_xlim(1e-4, 5)
    ax[0].set_xscale('log')
    ax[0].set_yscale('log')
    ax[1].set_xscale('log')
    ax[1].set_yscale('log')
    ax[0].set_xlabel('Gaia parallax', fontsize = fsize)
    ax[1].set_xlabel('Gaia parallax', fontsize = fsize)
    ax[0].set_ylabel('inferred parallax', fontsize = fsize)
    plt.savefig('plots/validation_parallax_inferred_log_{0}.pdf'.format(name))
    plt.close()
    
    dy = (labels['Q_K'] - labels['Q_pred']) / labels['Q_K']
    print('1 sigma Q: ', 0.5 * (np.percentile(dy, 84) - np.percentile(dy, 16)), 0.25 * (np.percentile(dy, 97.5) - np.percentile(dy, 2.5)))
    
    dy20 = (labels['Q_K'][best] - labels['Q_pred'][best]) / labels['Q_K'][best]
    print('1 sigma Q for best stars: ', 0.5 * (np.percentile(dy20, 84) - np.percentile(dy20, 16)), 0.25 * (np.percentile(dy20, 97.5) - np.percentile(dy20, 2.5)))
    
    plt.scatter(y_all[valid][cut20], y_pred[cut20], c = ivar_all[valid][cut20], cmap = 'Spectral', alpha = .6)
    plt.colorbar(label = r'$1/\sigma^2_Q$')
    ax[0].plot([-100, 100], [-100, 100], linestyle = '--', color = 'k')
    plt.ylim(0, np.max(y))
    plt.xlim(plt.ylim())
    low_Q_cut = np.where(y_pred[cut20] < 0.25)
    dy_low_Q = 0.5 * (np.percentile(dy20[low_Q_cut], 84) - np.percentile(dy20[low_Q_cut], 16))
    plt.axhline(0.25, linestyle = '--', color = 'k', label = r'$1\sigma = {}$'.format(round(dy_low_Q, 3)), zorder = 0)
    plt.xlabel(r'$Q_{K,\,\rm true}$', fontsize = 14)
    plt.ylabel(r'$Q_{K,\,\rm inferred}$', fontsize = 14)
    plt.legend()
    plt.title(r'$\varpi/\sigma_{{\varpi}} \geq 20: \lambda = {0}, 1\sigma = {1}$'.format(lam, round(0.5 * (np.percentile(dy20, 84) - np.percentile(dy20, 16)), 3)))
    plt.savefig('plots/validation_Q_{0}.pdf'.format(name))
    plt.close()

# -------------------------------------------------------------------------------
# infer parallaxes for all stars in parent sample
# -------------------------------------------------------------------------------





# -------------------------------------------------------------------------------
# improve parallaxes with Gaia parallaxes
# -------------------------------------------------------------------------------



                
# -------------------------------------------------------------------------------'''
                      
                       









