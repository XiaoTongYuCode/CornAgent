import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFile, writeFile } from 'node:fs/promises'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import type { Plugin } from 'vite'
import { ProjectIntroduction } from './src/app/ProjectIntroduction'
import { pageMetadata, publicHome, REPOSITORY_URL } from './src/app/seo'

const escape = (value: string) => value.replaceAll('&', '&amp;').replaceAll('"', '&quot;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')

function renderPage(html: string, path: string, siteUrl: string) {
  const meta = pageMetadata(path, 'en', siteUrl)
  const name = (key: string, value: string) => `<meta name="${key}" content="${escape(value)}" />`
  const property = (key: string, value: string) => `<meta property="${key}" content="${escape(value)}" />`
  const head = [
    `<title>${escape(meta.title)}</title>`, name('description', meta.description), name('robots', meta.robots),
    property('og:type', 'website'), property('og:site_name', 'CornAgent'), property('og:title', meta.title),
    property('og:description', meta.description), property('og:locale', 'en_US'),
    name('twitter:card', 'summary'), name('twitter:title', meta.title), name('twitter:description', meta.description),
    '<link rel="icon" type="image/svg+xml" href="/favicon.svg" />',
    ...(meta.canonical ? [
      `<link rel="canonical" href="${escape(meta.canonical)}" />`, property('og:url', meta.canonical),
      `<script id="project-structured-data" type="application/ld+json">${JSON.stringify(meta.structuredData).replaceAll('<', '\\u003c')}</script>`,
    ] : []),
  ].join('\n    ')
  const content = publicHome(path)
    ? `<main class="project-fallback">${renderToStaticMarkup(createElement(ProjectIntroduction, { locale: 'en' }))}</main>`
    : ''
  return html
    .replace(/<!--app-metadata:start-->[\s\S]*?<!--app-metadata:end-->/, () => `<!--app-metadata:start-->\n    ${head}\n    <!--app-metadata:end-->`)
    .replace(/<!--app-content:start-->[\s\S]*?<!--app-content:end-->/, () => `<!--app-content:start-->${content}<!--app-content:end-->`)
}

export function seoPlugin(siteUrl: string): Plugin {
  let outDir: string
  const documents: Record<string, string> = {
    'favicon.svg': readFileSync(new URL('../assets/brand/cornagent.svg', import.meta.url), 'utf8'),
    'robots.txt': `User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /metrics\nDisallow: /healthz\nDisallow: /readyz\n\nSitemap: ${siteUrl}/sitemap.xml\n`,
    'sitemap.xml': `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>${escape(siteUrl)}/</loc></url></urlset>\n`,
    'llms.txt': `# CornAgent\n\n> Open-source full-stack AI agent built with React and FastAPI.\n\nCornAgent is an embeddable, self-hosted AI agent runtime with a React chat page and agent sidebar. It supports SSE streaming, pause and resume, persistent execution state, and parallel multi-agent subtasks. PostgreSQL stores durable state; Redis Streams deliver live events. Components are distributed as source code, not a standalone npm package. The project uses the MIT license.\n\n## Project\n- [Website](${siteUrl}/)\n- [GitHub repository](${REPOSITORY_URL})\n- [Quick start](${REPOSITORY_URL}#quick-start)\n- [中文说明](${REPOSITORY_URL}/blob/main/README.zh-CN.md)\n\n## Documentation\n- [Embed the React agent sidebar](${REPOSITORY_URL}/blob/main/docs/frontend-integration.md)\n- [Runtime and recovery boundaries](${REPOSITORY_URL}/blob/main/docs/runtime.md)\n- [Parallel subtasks](${REPOSITORY_URL}/blob/main/docs/subagents.md)\n- [Self-hosting](${REPOSITORY_URL}/blob/main/docs/ecs-app.md)\n\n## Demos\n- [Chat](${siteUrl}/chat)\n- [Embeddable sidebar](${siteUrl}/sidebar)\n- [Rendering demo](${siteUrl}/rendering): Synthetic content, not real user conversations.\n`,
  }
  return {
    name: 'cornagent-search-metadata',
    configResolved(config) { outDir = resolve(config.root, config.build.outDir) },
    transformIndexHtml: {
      order: 'post',
      handler(html, context) {
        const path = context.originalUrl?.split('?')[0] ?? context.path
        return renderPage(html, path === '/index.html' ? '/' : path, siteUrl)
      },
    },
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const path = request.url?.split('?')[0] ?? ''
        if (!Object.hasOwn(documents, path.slice(1))) return next()
        const document = documents[path.slice(1)]
        if (!document) return next()
        response.setHeader('Content-Type', path.endsWith('.svg') ? 'image/svg+xml' : path.endsWith('.xml') ? 'application/xml; charset=utf-8' : 'text/plain; charset=utf-8')
        response.end(document)
      })
    },
    async writeBundle() {
      const index = await readFile(resolve(outDir, 'index.html'), 'utf8')
      for (const route of ['sidebar', 'rendering', 'usage', 'profile', 'app']) {
        await writeFile(resolve(outDir, `${route}.html`), renderPage(index, `/${route}`, siteUrl))
      }
      for (const [filename, content] of Object.entries(documents)) {
        await writeFile(resolve(outDir, filename), content)
      }
    },
  }
}
