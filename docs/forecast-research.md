# How operational centres combine weather models (roadmap 6.5)

A review of how operational centres and the literature combine several weather models
into one point forecast, written 2026-10-12 for our combined forecast (roadmap 6.2,
6.3); its method itself is not published. Sources at the end.

## What operational systems do

| System | Bias correction | Weights | Training data |
|---|---|---|---|
| Bureau of Meteorology, **Operational Consensus Forecasts** (Woodcock & Engel 2005), official guidance since 2005, 600+ sites, up to 8 models | per site and model, removed from the current forecast | inverse **MAE** of the bias-corrected model, recent performance | **30-day** running window |
| NOAA **National Blend of Models** | exponentially decaying average of each model's error | inverse MAE (Woodcock & Engel), also decaying average | decaying memory; MAE weighting was tested against equal weights, ridge regression and BMA on 335 stations and was "the most robust and easiest to run"; MAE-weighted blend more skilful than the equally weighted one |
| NCEP/NAEFS bias correction (Cui et al.) | decaying average, new error weighted **2 %** (memory about 50 days); 1 % and 10 % tested, 2 % best in most regions and seasons | – | initialised with the mean error of days T−46…T−17 |
| MeteoSwiss **Mixed EMOS** (Keller et al.) | regression per station and lead time | positive weights per station and lead time, fitted by CRPS | **45-day** rolling window ("worked well in sensitivity tests"); combining COSMO and IFS beat the better single post-processed model by about 9 % (CRPS) |

The established operational approach (OCF, NBM) is **bias correction plus
inverse-error weights per site and lead time**. Two choices matter:

1. **Training length.** Operational systems use about **30–50 days**: model biases
   change with season, weather regime and model upgrades. Cheng & Steenburgh (2007)
   found that short running-mean bias removal and Kalman filters work well in
   persistent regimes (valley cold pools) but lag when the regime changes; long MOS
   training handled sharp changes better. Short windows adapt, long windows are stable.
2. **Inverse MAE vs inverse error variance.** Woodcock & Greenslade (2007) report
   that the choice makes a negligible difference.

## The risk: estimated weights can lose to a plain average

The "forecast combination puzzle" (Stock & Watson 2004; Smith & Wallis 2009; Qian et
al. 2015): a simple average often beats estimated "optimal" weights, because weights
estimated from short samples carry noise that can cost more than they gain. Estimated
weights pay off when one model is clearly better or when there is a lot of data.
Consequences:

- **Shrinking towards the plain mean** is the cautious choice while the scores are short.
- **The models are not independent.** IFS HRES, IFS 0.25° and AIFS share ECMWF's
  analysis; ICON-D2 and ICON-EU are both DWD; the two ALADINs are both ČHMÚ. Weights
  that ignore this give a model family several votes. Inverse-error weights do not
  correct for correlated errors; only weights fitted jointly (regression, EMOS) do, and
  those need much more data.
- **It must be tested, not assumed** (roadmap 6.4): weights estimated only from days
  before the scored day, scored like a model, compared with the best single model and
  the plain mean, with the day-bootstrap intervals we already use for the ranking
  (`blend-test.json`, the Compare page; [methodology.md](methodology.md#our-own-forecast)).

## Precipitation

Averaging rain fields smooths them: the mean of several models forecasts light rain
too often and heavy rain too weakly (Clark 2017; probability matching, Ebert 2001,
is the usual remedy for gridded fields). For a point forecast this means a combined
hourly rain shows drizzle where only some models have a shower, and understates a
downpour. Remedies that fit a TV-style forecast: show the **probability
of precipitation** (the share of models that forecast rain) next to the
amount, and draw rain symbols only when that probability is high.

## Models that stop early

ICON-D2, AROME and ALADIN end after 1–3 days. When a model drops out, the remaining
weights are rescaled and the combined curve can jump. MeteoSwiss tapers the outgoing
model over its last hours (they tested two schemes; carrying the model's correction
forward with decaying weight was best).

## Sources

- Woodcock, F. & Engel, C. (2005): Operational consensus forecasts. *Weather and
  Forecasting* 20, 101–111. Summarised in Woodcock & Greenslade (2007), *Weather and
  Forecasting* 22: <https://data-ww3.ifremer.fr/BIB/Woodcock_Greenslade_WF2007.pdf>
- Bureau of Meteorology OCF description (30-day window, up to 8 models):
  <https://australianweathernews.com/sitepages/forecasts/forecast_OCF_help.htm>
- NOAA MDL, National Blend of Models: weighting (decaying-average MAE weights, tests
  against equal weights, ridge regression and BMA):
  <https://www.weather.gov/media/mdl/Veenhuis_Presentation2015.pdf>,
  <https://blend.mdl.nws.noaa.gov/nbm-documentation>
- Cui, B. et al.: Bias correction for global ensemble forecast (decaying average, 2 %):
  <https://www.emc.ncep.noaa.gov/gmb/ens/papers/manuscript_thorpex_bocui.pdf>
- Keller, R. et al. (2021): Seamless multi-model postprocessing for air temperature
  forecasts in complex topography (MeteoSwiss, 45-day window, tapering):
  <https://arxiv.org/abs/2008.07857>
- Cheng, W. Y. Y. & Steenburgh, W. J. (2007): Strengths and weaknesses of MOS,
  running-mean bias removal, and Kalman filter techniques. *Weather and Forecasting*
  22, 1304–1318:
  <https://impacts.ucar.edu/en/publications/strengths-and-weaknesses-of-mos-running-mean-bias-removal-and-kal/>
- Qian, W. et al. (2015): On the forecast combination puzzle (review of Stock & Watson
  2004, Smith & Wallis 2009, Claeskens et al.): <https://arxiv.org/abs/1505.00475>
- Clark, A. J. (2017): Generation of ensemble mean precipitation forecasts from
  convection-allowing ensembles. *Weather and Forecasting* 32, 1569–1583:
  <https://repository.library.noaa.gov/view/noaa/32308>
