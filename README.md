# Roads & Railways of Armenia

Interactive OpenStreetMap map of Armenia's roads (speed limit, surface, lighting, track grade) and railways (type, gauge, electrification, usage, tracks). Static site: no server, no build step for the page.

## Structure

```
index.html                     the whole map (MapLibre GL, one file)
robots.txt, sitemap.xml        SEO (regenerated monthly by the data build)
og-image.png                   social preview image
scripts/build_data.py          downloads OSM data via Overpass -> data/
scripts/config.json            country settings (relation id, languages, admin level)
data/                          generated GeoJSON + meta.json (created by the workflow)
.github/workflows/
  update-data.yaml             monthly data refresh (1st, 03:00 UTC) or manual run
  pages.yml                    deploys the site to GitHub Pages
```

## Setup (once, about 5 minutes)

1. Create a **public** repository and push these files to the `main` branch.
2. **Settings -> Pages -> Build and deployment -> Source: GitHub Actions.**
3. **Actions -> "Deploy site to GitHub Pages" -> Run workflow.** The site goes live at `https://<user>.github.io/<repo>/` (your real URL is filled into the canonical, sitemap and structured data automatically).
4. **Actions -> "Update Armenia road & rail data" -> Run workflow.** The first build takes roughly 30-90 minutes. It commits `data/` and redeploys the site. Until then the page loads live from OpenStreetMap.
5. Custom domain? Add a repository variable `SITE_URL` (Settings -> Variables), e.g. `https://roads.example.am/`, and re-run the deploy workflow.

## SEO checklist after launch

- Add the site in Google Search Console and Bing Webmaster Tools, then submit `<your-url>/sitemap.xml`.
- Set the repository description and topics (`armenia`, `openstreetmap`, `roads`, `railways`, `geojson`).
- Share the link on the OSM wiki/forum and Armenian GIS or transport communities.

## Safety nets

The data build exits without committing if any query fails or any layer shrinks by more than 20 percent, so a bad run never replaces good data. Local roads load per region only for the area in view.

## Licence

Code: MIT. Data: (c) OpenStreetMap contributors, ODbL 1.0.
