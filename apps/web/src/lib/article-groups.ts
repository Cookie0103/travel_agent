/** Group guide sections by destination for browsing; well-known cities first, then first appearance. */
import type { Article } from "./api";

const SEP = " · ";

// 快照城市名保持 Wikivoyage 原标题（简繁混用），排序表两种写法都列。
const CITY_ORDER = [
  ["東京", "东京"],
  ["京都"],
  ["大阪"],
  ["奈良"],
  ["神戶", "神户"],
  ["箱根"],
  ["鎌倉", "镰仓"],
  ["名古屋"],
  ["金澤", "金泽"],
  ["廣島", "广岛"],
  ["福岡", "福冈"],
  ["長崎", "长崎"],
  ["札幌"],
  ["那霸"],
];
const rank = (city: string) => {
  const i = CITY_ORDER.findIndex((names) => names.includes(city));
  return i < 0 ? CITY_ORDER.length : i;
};

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
  // sort 是稳定排序：表外城市保持出现顺序，排在表内城市之后。
  return [...groups]
    .map(([city, items]) => ({ city, items }))
    .sort((a, b) => rank(a.city) - rank(b.city));
}
