# MeteoVerdict on a TRMNL

`full.liquid` is a TRMNL private plugin (OG, 800×480, black and white) that shows
**today and tomorrow** for one okres:

- weather symbol, high and low, a one-word summary, sunrise and sunset
- rain (mm and chance), hours of sunshine out of the day's daylight, cloud cover, wind
- night, morning, afternoon and evening with their own symbols (a moon at night)
- the hourly temperature curve with rain bars, night hatched from sunset to sunrise and a
  dashed line at the current time

The forecast is MeteoVerdict's combined forecast from the open data, refreshed at 05:52
and 17:52 UTC.

## Set it up

1. In TRMNL go to **Plugins → Private Plugin → Add new**.
2. **Strategy:** Polling. **Polling URL** (your okres instead of `CZ0100`, Prague; every
   code is in [api/v1/index.json](https://jerrywoof.github.io/MeteoVerdict/api/v1/index.json)):

   ```
   https://jerrywoof.github.io/MeteoVerdict/api/v1/okresy/CZ0100.json
   ```

3. **Refresh rate:** hourly (the curve's "now" line moves; the forecast changes twice a day).
4. **Edit Markup → Full:** paste `full.liquid`, put your town in `place` at the top if you like,
   save, and click **Force Refresh**.
5. Add the plugin to a playlist.

"Today" uses the time zone of your TRMNL account. If the newest forecast does not contain
that date yet, the screen shows the first two days of the forecast.

## Preview locally

```bash
npm i liquidjs@10 && node preview.mjs full.liquid preview.html CZ0100
```

Add `test` as the last argument to see every weather symbol, rain, and today without its
whole-day row.

Data: MeteoVerdict (CC BY-SA 4.0), Open-Meteo.com and ČHMÚ.
