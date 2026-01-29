"use client";

import { useEffect, useState } from "react";
import { api, NewsSource, NewsArticle, ArticleContext } from "@/lib/api";
import { formatDateTime, formatRelativeTime } from "@/lib/utils";
import { Header } from "@/components/layout/Header";
import { Button, Card, LoadingPage } from "@/components/ui";

const contextColors: Record<ArticleContext, string> = {
  "race-weekend": "bg-racing-red/20 text-racing-red",
  "off-week": "bg-cyber-purple/20 text-cyber-purple",
  "breaking": "bg-warning-yellow/20 text-warning-yellow",
  "feature": "bg-electric-blue/20 text-electric-blue",
};

export default function NewsPage() {
  const [sources, setSources] = useState<NewsSource[]>([]);
  const [articles, setArticles] = useState<NewsArticle[]>([]);
  const [loading, setLoading] = useState(true);
  const [scraping, setScraping] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<ArticleContext | "all">("all");
  const [showUsed, setShowUsed] = useState<boolean | undefined>(undefined);

  useEffect(() => {
    fetchData();
  }, [filter, showUsed]);

  async function fetchData() {
    try {
      setLoading(true);
      
      const [sourcesData, articlesData] = await Promise.all([
        api.news.listSources(),
        api.news.listArticles({
          context: filter === "all" ? undefined : filter,
          used: showUsed,
          limit: 100,
        }),
      ]);
      
      setSources(sourcesData);
      setArticles(articlesData);
      setError(null);
    } catch (err) {
      console.error("Failed to fetch news data:", err);
      setError(err instanceof Error ? err.message : "Failed to load news");
    } finally {
      setLoading(false);
    }
  }

  async function handleScrape(contextType: string) {
    try {
      setScraping(true);
      const focusAreas = contextType === "off-week" 
        ? ["paddock_news", "transfers", "technical_developments", "paddock_gossip"]
        : ["race_results", "driver_quotes", "team_drama", "driver_battles"];
      
      const result = await api.news.scrape({
        context_type: contextType,
        focus_areas: focusAreas,
        date_range_days: contextType === "off-week" ? 7 : undefined,
        date_range_hours: contextType !== "off-week" ? 48 : undefined,
        max_articles: 30,
      });
      
      alert(`Scraped ${result.articles_scraped} articles from ${result.sources_checked} sources`);
      await fetchData();
    } catch (err) {
      console.error("Scrape failed:", err);
      setError(err instanceof Error ? err.message : "Scrape failed");
    } finally {
      setScraping(false);
    }
  }

  async function toggleSource(sourceId: number, isActive: boolean) {
    try {
      await api.news.updateSource(sourceId, { is_active: !isActive });
      await fetchData();
    } catch (err) {
      console.error("Failed to update source:", err);
    }
  }

  if (loading) {
    return <LoadingPage text="Loading news feed..." />;
  }

  return (
    <div className="space-y-8">
      <Header
        title="News Feed"
        subtitle="F1 news sources and scraped articles"
        actions={
          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => handleScrape("race-weekend")} disabled={scraping}>
              {scraping ? "Scraping..." : "Scrape Race News"}
            </Button>
            <Button onClick={() => handleScrape("off-week")} disabled={scraping}>
              {scraping ? "Scraping..." : "Scrape Off-Week News"}
            </Button>
          </div>
        }
      />

      {error && (
        <div className="rounded-lg border border-racing-red/50 bg-racing-red/10 p-4">
          <p className="text-racing-red">{error}</p>
        </div>
      )}

      {/* News Sources */}
      <section>
        <h2 className="mb-4 text-xl font-semibold text-white">News Sources</h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {sources.map((source) => (
            <Card key={source.id} className={`p-4 ${!source.is_active ? "opacity-50" : ""}`}>
              <div className="flex items-start justify-between">
                <div>
                  <h3 className="font-medium text-white">{source.name}</h3>
                  <p className="mt-1 text-xs text-white/60">
                    Priority: {source.priority}/10
                  </p>
                  {source.last_scraped_at && (
                    <p className="mt-1 text-xs text-white/40">
                      Last scraped: {formatRelativeTime(source.last_scraped_at)}
                    </p>
                  )}
                </div>
                <button
                  onClick={() => toggleSource(source.id, source.is_active)}
                  className={`rounded-full p-1 transition-colors ${
                    source.is_active 
                      ? "bg-success-green/20 text-success-green hover:bg-success-green/30" 
                      : "bg-white/10 text-white/40 hover:bg-white/20"
                  }`}
                >
                  <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 20 20">
                    {source.is_active ? (
                      <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                    ) : (
                      <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
                    )}
                  </svg>
                </button>
              </div>
            </Card>
          ))}
        </div>
      </section>

      {/* Articles */}
      <section>
        <div className="mb-4 flex flex-wrap items-center justify-between gap-4">
          <h2 className="text-xl font-semibold text-white">Scraped Articles ({articles.length})</h2>
          
          <div className="flex flex-wrap gap-2">
            {/* Context filter */}
            {(["all", "race-weekend", "off-week", "breaking", "feature"] as const).map((ctx) => (
              <button
                key={ctx}
                onClick={() => setFilter(ctx)}
                className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                  filter === ctx
                    ? "bg-neon-cyan/20 text-neon-cyan"
                    : "text-white/60 hover:bg-white/5 hover:text-white"
                }`}
              >
                {ctx === "all" ? "All" : ctx.charAt(0).toUpperCase() + ctx.slice(1).replace("-", " ")}
              </button>
            ))}
            
            <span className="mx-2 border-l border-white/20" />
            
            {/* Used filter */}
            <button
              onClick={() => setShowUsed(showUsed === undefined ? false : showUsed === false ? true : undefined)}
              className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                showUsed !== undefined
                  ? "bg-neon-cyan/20 text-neon-cyan"
                  : "text-white/60 hover:bg-white/5 hover:text-white"
              }`}
            >
              {showUsed === undefined ? "All" : showUsed ? "Used" : "Unused"}
            </button>
          </div>
        </div>

        <div className="space-y-3">
          {articles.map((article) => (
            <Card key={article.id} className="p-4">
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={`rounded px-2 py-0.5 text-xs font-medium ${contextColors[article.context]}`}>
                      {article.context.replace("-", " ")}
                    </span>
                    {article.used_in_episode_id && (
                      <span className="rounded bg-success-green/20 px-2 py-0.5 text-xs text-success-green">
                        Used
                      </span>
                    )}
                    {article.source_name && (
                      <span className="text-xs text-white/40">{article.source_name}</span>
                    )}
                  </div>
                  
                  <a 
                    href={article.url} 
                    target="_blank" 
                    rel="noopener noreferrer"
                    className="mt-2 block font-medium text-white hover:text-neon-cyan"
                  >
                    {article.title}
                  </a>
                  
                  {article.summary && (
                    <p className="mt-1 text-sm text-white/60 line-clamp-2">{article.summary}</p>
                  )}
                  
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-white/40">
                    {article.published_at && (
                      <span>{formatRelativeTime(article.published_at)}</span>
                    )}
                    {article.mentioned_drivers && article.mentioned_drivers.length > 0 && (
                      <>
                        <span>•</span>
                        <span>Drivers: {article.mentioned_drivers.join(", ")}</span>
                      </>
                    )}
                    {article.mentioned_teams && article.mentioned_teams.length > 0 && (
                      <>
                        <span>•</span>
                        <span>Teams: {article.mentioned_teams.join(", ")}</span>
                      </>
                    )}
                  </div>
                </div>
                
                <div className="flex gap-2">
                  <a
                    href={article.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="rounded p-2 text-white/40 hover:bg-white/10 hover:text-white"
                  >
                    <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                    </svg>
                  </a>
                </div>
              </div>
            </Card>
          ))}
          
          {articles.length === 0 && (
            <Card className="p-8 text-center">
              <svg className="mx-auto h-12 w-12 text-white/20" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 20H5a2 2 0 01-2-2V6a2 2 0 012-2h10a2 2 0 012 2v1m2 13a2 2 0 01-2-2V7m2 13a2 2 0 002-2V9a2 2 0 00-2-2h-2m-4-3H9M7 16h6M7 8h6v4H7V8z" />
              </svg>
              <h3 className="mt-4 text-lg font-medium text-white">No articles found</h3>
              <p className="mt-2 text-white/60">Scrape news to populate the feed</p>
            </Card>
          )}
        </div>
      </section>
    </div>
  );
}
