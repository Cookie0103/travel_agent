/** Read attributed guide snapshots as plain text, then explicitly enter the chat. */
"use client";
import { Loading } from "./ui/loading";
import { Button } from "./ui/button";
import Link from "next/link";
import { sourceHref } from "@/lib/api";
import { Banner } from "./banner";
import { useArticles } from "@/lib/use-articles";

export function Articles({ articleId }: { articleId?: string }) {
  const guide = useArticles(articleId);
  return (
    <main className="page">
      <h1>来源资料</h1>
      <p className="notice">
        攻略来自 Wikivoyage
        历史快照。文章是参考资料，营业时间、价格与当前条件仍需工具核验。
      </p>
      {articleId && <Link href="/articles">返回全部来源资料</Link>}
      {guide.loading && <Loading>正在读取攻略…</Loading>}
      {guide.error && (
        <Banner kind="error">
          {guide.error}{" "}
          <Button variant="outline" onClick={guide.retry}>
            重新读取攻略
          </Button>
        </Banner>
      )}
      {!guide.loading && !guide.error && !guide.articles.length && (
        <p>暂时没有来源资料，可以先回到对话。</p>
      )}
      <div className="guide-grid">
        {guide.articles.map((article) => (
          <article className="guide-card" key={article.article_id}>
            <span className="tag">京都 · 历史快照</span>
            <h2>{article.title}</h2>
            {articleId ? (
              <p className="guide-text">{article.text}</p>
            ) : (
              <p>
                {article.text.slice(0, 180)}
                {article.text.length > 180 ? "…" : ""}
              </p>
            )}
            <p className="muted small">
              {article.source.attribution} · {article.source.license}
              <br />
              获取时间：{article.source.retrieved_at}
              <br />
              来源版本：{article.source.content_version.slice(0, 12)}
            </p>
            <p className="small">
              <a
                href={sourceHref(article.source.source_ref)}
                target="_blank"
                rel="noopener noreferrer"
              >
                查看原始来源
              </a>{" "}
              ·{" "}
              <a
                href={sourceHref(article.source.license_url)}
                target="_blank"
                rel="noopener noreferrer"
              >
                许可条款
              </a>
            </p>
            <div className="guide-actions">
              {!articleId && (
                <Link
                  href={`/articles/${encodeURIComponent(article.article_id)}`}
                >
                  阅读全文
                </Link>
              )}
              <Link
                href={`/?article=${encodeURIComponent(article.article_id)}`}
              >
                基于这篇提问
              </Link>
            </div>
          </article>
        ))}
      </div>
    </main>
  );
}

export function ArticleReference({
  articleId,
  select,
}: {
  articleId: string;
  select: (id: string) => void;
}) {
  const guide = useArticles(articleId);
  const article = guide.articles[0];
  return (
    <section className="guide-reference">
      {guide.loading && <Loading>正在读取参考攻略…</Loading>}
      {guide.error && (
        <p role="alert">
          {guide.error}{" "}
          <Button variant="outline" onClick={guide.retry}>
            重新读取攻略
          </Button>
        </p>
      )}
      {article && (
        <>
          <p>参考攻略：{article.title} · 历史快照</p>
          <Button variant="outline" onClick={() => select(article.article_id)}>
            把攻略引用填入消息
          </Button>
          <p className="muted small">
            只填入引用，不自动发送或保存；请补充你的条件后再发送。
          </p>
        </>
      )}
    </section>
  );
}
