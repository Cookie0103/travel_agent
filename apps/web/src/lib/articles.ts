/** Article provenance labels come from each snapshot's own provider field. */
import type { Article } from "./api";

const providers: Record<Article["source"]["provider"], string> = {
  wikivoyage: "Wikivoyage",
  osm: "OpenStreetMap",
  google_places: "Google Places",
  synthetic: "合成数据",
};

export const providerLabel = (provider: Article["source"]["provider"]) =>
  providers[provider];

export const sourceNames = (articles: readonly Article[]) =>
  [
    ...new Set(
      articles.map((article) => providerLabel(article.source.provider)),
    ),
  ].join("、");
