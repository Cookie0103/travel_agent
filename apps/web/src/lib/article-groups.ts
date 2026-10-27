/** Group guide sections by destination for browsing; order follows first appearance. */
import type { Article } from "./api";

const SEP = " · ";

/** City from the snapshot's own field, else the title prefix before " · ". */
export const articleCity = (article: Pick<Article, "city" | "title">) =>
  article.city?.trim() ||
  (article.title.includes(SEP) ? article.title.split(SEP)[0] : "其他");

/** Section heading without a repeated "城市 · " prefix. */
export const sectionTitle = (article: Pick<Article, "city" | "title">) => {
  const prefix = `${articleCity(article)}${SEP}`;
  return article.title.startsWith(prefix)
    ? article.title.slice(prefix.length) || article.title
    : article.title;
};

export function groupByCity<T extends Pick<Article, "city" | "title">>(
  articles: readonly T[],
) {
  const groups = new Map<string, T[]>();
  for (const article of articles) {
    const city = articleCity(article);
    const list = groups.get(city);
    if (list) list.push(article);
    else groups.set(city, [article]);
  }
  return [...groups].map(([city, items]) => ({ city, items }));
}
