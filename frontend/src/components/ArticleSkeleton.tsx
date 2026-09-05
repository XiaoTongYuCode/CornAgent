import { Skeleton } from 'antd'

/** Decorative article layout for embedding examples and loading placeholders. */
export function ArticleSkeleton() {
  return (
    <div className="article-skeleton" aria-hidden="true">
      <Skeleton
        avatar={{ size: 36 }}
        title={{ width: 112 }}
        paragraph={{ rows: 1, width: 180 }}
        round
      />
      <Skeleton.Node className="article-skeleton__cover" style={{ width: '100%', height: '100%' }} />
      <Skeleton title={false} paragraph={{ rows: 4, width: ['100%', '96%', '100%', '72%'] }} round />
      <Skeleton title={{ width: '38%' }} paragraph={{ rows: 3, width: ['100%', '100%', '84%'] }} round />
      <Skeleton title={{ width: '30%' }} paragraph={{ rows: 3, width: ['100%', '94%', '62%'] }} round />
    </div>
  )
}
