/** Read attributed guide snapshots as plain text, then explicitly enter the chat. */
"use client";
import { Loading } from "./ui/loading";
import { Button } from "./ui/button";
import Link from "next/link";
import { useMemo, useState } from "react";
import { sourceHref, type Article } from "@/lib/api";
import { Banner } from "./banner";
import { useArticles } from "@/lib/use-articles";
import { sourceNames } from "@/lib/articles";
import { articleCity, groupByCity, sectionTitle } from "@/lib/article-groups";
import { formatTokyo } from "@/lib/format-time";

/** Sections shown per city before "展开更多". */
const PREVIEW = 8;

const readHref = (id: string) => `/articles/${encodeURIComponent(id)}`;
const askHref = (id: string) => `/?article=${encodeURIComponent(id)}`;

function Provenance({ article }: { article: Article }) {
  return (
    <div className="guide-source">
      <p>
        {article.source.attribution} · {article.source.license}
      </p>
      <p>
        获取时间：{formatTokyo(article.source.retrieved_at)} · 来源版本：
        {article.source.content_version.slice(0, 12)}
      </p>
      <p>
        <a
          href={sourceHref(article.source.source_ref)}
          target="_blank"
          rel="noopener noreferrer"
        >
          查看原始来源
        </a>
        {" · "}
        <a
          href={sourceHref(article.source.license_url)}
          target="_blank"
          rel="noopener noreferrer"
        >
          许可条款
        </a>
      </p>
    </div>
  );
}

function GuideCard({ article }: { article: Article }) {
  return (
    <article className="guide-card">
      <span className="tag">{article.city} · 历史快照</span>
      <h3 title={article.title}>
        <Link href={readHref(article.article_id)}>{sectionTitle(article)}</Link>
      </h3>
      <p className="guide-excerpt">
        {article.text.slice(0, 180)}
        {article.text.length > 180 ? "…" : ""}
      </p>
      <Provenance article={article} />
      <div className="guide-actions">
        <Link className="link-button" href={readHref(article.article_id)}>
          阅读全文
        </Link>
        <Link
          className="link-button is-quiet"
          href={askHref(article.article_id)}
        >
          基于这篇提问
        </Link>
      </div>
    </article>
  );
}

function CardSkeleton({ count }: { count: number }) {
  return (
    <div className="guide-grid" aria-hidden="true">
      {Array.from({ length: count }, (_, i) => (
        <div className="skeleton-card" key={i}>
          <span />
          <span />
          <span />
          <span />
        </div>
      ))}
    </div>
  );
}

function SourceNote({ names }: { names: string }) {
  return (
    <p className="notice info-callout">
      攻略来自{names ? ` ${names} ` : ""}
      历史快照。文章是参考资料，营业时间、价格与当前条件仍需工具核验。
    </p>
  );
}

export function Articles({ articleId }: { articleId?: string }) {
  const guide = useArticles(articleId);
  const names = sourceNames(guide.articles);
  const [city, setCity] = useState<string>();
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());
  const groups = useMemo(() => groupByCity(guide.articles), [guide.articles]);
  const shown = groups.filter((group) => !city || group.city === city);
  const toggle = (name: string) =>
    setExpanded((old) => {
      const next = new Set(old);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });

  const status = (
    <>
      {guide.loading && (
        <div role="status">
          <p className="muted small">正在读取攻略…</p>
          <CardSkeleton count={articleId ? 1 : 6} />
        </div>
      )}
      {guide.error && (
        <Banner kind="error">
          {guide.error}{" "}
          <Button variant="outline" onClick={guide.retry}>
            重新读取攻略
          </Button>
        </Banner>
      )}
      {!guide.loading && !guide.error && !guide.articles.length && (
        <div className="empty-state page-empty">
          <p>暂时没有来源资料，可以先回到对话。</p>
          <Link className="link-button" href="/">
            回到对话
          </Link>
        </div>
      )}
    </>
  );

  if (articleId) {
    const article = guide.articles[0];
    return (
      <main className="page page-wide" id="main-content" tabIndex={-1}>
        <div className="guide-reader">
          <nav className="breadcrumb" aria-label="面包屑">
            <Link href="/articles">返回全部来源资料</Link>
            {article && (
              <>
                <span aria-hidden="true">/</span>
                <span>{articleCity(article)}</span>
                <span aria-hidden="true">/</span>
                <span aria-current="page">{sectionTitle(article)}</span>
              </>
            )}
          </nav>
          {!article && <h1>来源资料</h1>}
          {status}
          {article && (
            <article>
              <span className="tag">{article.city} · 历史快照</span>
              <h1>{article.title}</h1>
              <SourceNote names={names} />
              <p className="guide-text">{article.text}</p>
              <div className="guide-actions">
                <Link
                  className="link-button"
                  href={askHref(article.article_id)}
                >
                  基于这篇提问
                </Link>
                <Link className="link-button is-quiet" href="/articles">
                  浏览其他攻略
                </Link>
              </div>
              <footer className="guide-footer">
                <h2>来源与许可</h2>
                <Provenance article={article} />
              </footer>
            </article>
          )}
        </div>
      </main>
    );
  }

  return (
    <main className="page page-wide" id="main-content" tabIndex={-1}>
      <header className="page-header">
        <h1>来源资料</h1>
        <p className="page-lede">
          按目的地浏览攻略片段，阅读全文或带入对话提问。
        </p>
        <SourceNote names={names} />
      </header>
      {status}
      {groups.length > 1 && (
        <div className="filter-chips" role="group" aria-label="按城市筛选">
          <button
            type="button"
            aria-pressed={!city}
            onClick={() => setCity(undefined)}
          >
            全部<span>{guide.articles.length}</span>
          </button>
          {groups.map((group) => (
            <button
              type="button"
              key={group.city}
              aria-pressed={city === group.city}
              onClick={() => setCity(group.city)}
            >
              {group.city}
              <span>{group.items.length}</span>
            </button>
          ))}
        </div>
      )}
      {shown.map((group) => {
        const open = expanded.has(group.city);
        const rest = group.items.length - PREVIEW;
        const items = open ? group.items : group.items.slice(0, PREVIEW);
        return (
          <section
            className="city-group"
            key={group.city}
            aria-label={`${group.city}攻略`}
          >
            <div className="section-head">
              <h2>{group.city}</h2>
              <span className="count-chip">{group.items.length} 篇</span>
            </div>
            <div className="guide-grid">
              {items.map((item) => (
                <GuideCard article={item} key={item.article_id} />
              ))}
            </div>
            {rest > 0 && (
              <div className="group-more">
                <Button variant="outline" onClick={() => toggle(group.city)}>
                  {open ? "收起" : `展开更多 (${rest})`}
                </Button>
              </div>
            )}
          </section>
        );
      })}
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
