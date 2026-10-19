// The text of the pages About, Methodology and For business, in Czech and English: lists of
// blocks (see renderBlocks in info-page.js). Links: [text](url), bold: **text**.

const REPO = "https://github.com/JerryWoof/MeteoVerdict";

export const PAGES = {
  about: {
    cs: {
      title: "O projektu",
      blocks: [
        ["p", "MeteoVerdict je český web o počasí s jednou nezvyklou otázkou: **kterému předpovědnímu modelu v Česku věřit a trefil se?** Každý den porovnáváme předpovědi desítek modelů (ALADIN, ICON, ECMWF a další) s tím, co naměřily stanice ČHMÚ, a výsledek ukazujeme na mapě po okresech."],
        ["h", "Co tu najdete"],
        ["ul", [
          "**[Předpověď](forecast.html)** pro každý okres a pro 6 258 obcí. Skládáme ji z modelů podle toho, jak přesně v daném okrese v poslední době předpovídaly. Předpověď pro obce je zatím ve zkušebním provozu.",
          "**[Mapa přesnosti](./)** a **[Porovnání](compare.html)**: který model vede kde, pro jakou veličinu a jak jisté to pořadí je.",
          "**[Radar](radar.html)** a **[Naměřeno](measured.html)**: radar ČHMÚ a měření stanic.",
          "**[AI předpověď](ai.html)** a **[AI teplotní mapa](heatmap.html)**: experimentální modely, které ověřujeme stejně přísně jako ostatní.",
          "**[Otevřená data](data.html)**: předpověď a skóre modelů pro každý okres jako JSON a CSV, zdarma.",
        ]],
        ["h", "Odkud jsou data a kolik jim věřit"],
        ["p", "Měření jsou z otevřených dat ČHMÚ, předpovědi modelů z Open-Meteo. Skóre je poctivé, ale zatím krátkodobé: počítáme je z posledních týdnů a měsíců, takže pořadí se může obrátit. Jak přesně počítáme a kde jsou hranice, popisuje [metodika]("+REPO+"/blob/main/docs/methodology.md)."],
        ["h", "Otevřenost"],
        ["p", "Kód je otevřený a leží na [GitHubu]("+REPO+"). Skóre jsou pod licencí CC BY-SA 4.0, zdroje dat mají své licence (ČHMÚ a Open-Meteo CC BY 4.0), uvedené v patičce každé stránky. Součástí projektu je i to, že zveřejňujeme také experimenty, které nevyšly."],
        ["h", "Kontakt", "contact"],
        ["p", "Chyby, nápady a dotazy nejlépe napište jako [issue na GitHubu]("+REPO+"/issues): vidí je i ostatní a nic se neztratí. Spolupráce a pilotní provoz pro firmy jsou popsané na stránce Pro firmy."],
      ],
    },
    en: {
      title: "About",
      blocks: [
        ["p", "MeteoVerdict is a Czech weather site built around one unusual question: **which forecast model should you trust in Czechia, and did it get it right?** Every day we compare the forecasts of dozens of models (ALADIN, ICON, ECMWF and others) with what the ČHMÚ stations measured, and show the result on a map by okres."],
        ["h", "What you will find"],
        ["ul", [
          "**[Forecast](forecast.html)** for every okres and for 6,258 municipalities. We combine the models by how accurately each has forecast that okres lately. The municipality forecast is still a test.",
          "**[The accuracy map](./)** and **[Compare](compare.html)**: which model leads where, for which variable, and how sure that ranking is.",
          "**[Radar](radar.html)** and **[Measured](measured.html)**: ČHMÚ's radar and the stations' measurements.",
          "**[AI forecast](ai.html)** and **[AI heatmap](heatmap.html)**: experimental models, checked as strictly as the others.",
          "**[Open data](data.html)**: the forecast and the model scores for every okres as JSON and CSV, free.",
        ]],
        ["h", "Where the data comes from and how far to trust it"],
        ["p", "Measurements are ČHMÚ's open data, model forecasts come from Open-Meteo. The scores are honest but still short-term: they cover the last weeks and months, so a ranking can flip. How we compute them and where the limits are is in the [methodology]("+REPO+"/blob/main/docs/methodology.md)."],
        ["h", "Openness"],
        ["p", "The code is open, on [GitHub]("+REPO+"). The scores are CC BY-SA 4.0; each source has its own licence (ČHMÚ and Open-Meteo CC BY 4.0), listed in every page's footer. We also publish the experiments that did not work."],
        ["h", "Contact", "contact"],
        ["p", "Bugs, ideas and questions are best sent as an [issue on GitHub]("+REPO+"/issues): others can see them and nothing gets lost. Collaboration and pilots for companies are described on the For business page."],
      ],
    },
  },
};
