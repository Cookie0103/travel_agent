/** Public snapshot reads are cancellable views; they never create a session or send a message. */
"use client";
import { useEffect, useState } from "react";
import { api, type Article } from "./api";

export function useArticles(articleId?: string) {
  const path = articleId
    ? `/articles/${encodeURIComponent(articleId)}`
    : "/articles";
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState({
    key: "",
    articles: [] as Article[],
    error: "",
  });
  const key = `${path}:${attempt}`;
  useEffect(() => {
    let active = true;
    const request = articleId
      ? api<Article>(path).then((article) => [article])
      : api<Article[]>(path);
    void request.then(
      (articles) => {
        if (active) setResult({ key, articles, error: "" });
      },
      (error: unknown) => {
        if (active)
          setResult({
            key,
            articles: [],
            error: error instanceof Error ? error.message : "攻略读取失败",
          });
      },
    );
    return () => {
      active = false;
    };
  }, [path, key, articleId]);
  const pending = result.key !== key;
  return {
    loading: pending,
    articles: pending ? [] : result.articles,
    error: pending ? "" : result.error,
    retry: () => setAttempt((old) => old + 1),
  };
}
