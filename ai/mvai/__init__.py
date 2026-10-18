"""MeteoVerdict AI: experimental machine-learning forecasts (the site's "AI forecast" tab).

Trained on the DGX Spark from the archive of every model's D+N forecasts and the ČHMÚ
observations; every experiment is scored out of sample by ``mvd blend-test --candidate``
against the combined forecast and the best single model before it is shown as working.
"""
