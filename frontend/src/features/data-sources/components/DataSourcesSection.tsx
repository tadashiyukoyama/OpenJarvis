import { useDataSourcesController } from '../hooks/useDataSourcesController';
import { AvailableSources } from './AvailableSources';
import { ConnectedSources } from './ConnectedSources';
import { JarvisProviderOverview } from './JarvisProviderOverview';

function SourcesSkeleton() {
  return (
    <section>
      <div className="hud-label mb-2" style={{ color: 'var(--color-text-tertiary)' }}>
        Loading sources…
      </div>
      <div className="flex flex-col gap-2">
        {[0, 1, 2, 3].map((item) => (
          <div
            key={item}
            className="hud-panel data-skeleton"
            style={{ padding: '14px 18px', height: 60, opacity: 0.6 - item * 0.08 }}
          />
        ))}
      </div>
    </section>
  );
}

export function DataSourcesSection() {
  const sources = useDataSourcesController();
  if (sources.isFirstLoad) return <SourcesSkeleton />;
  return (
    <div className="flex flex-col gap-5">
      <JarvisProviderOverview />
      <ConnectedSources
        sources={sources.connected}
        statuses={sources.syncStatuses}
        disconnectingId={sources.disconnectingId}
        onDisconnect={sources.handleDisconnect}
        onRefresh={sources.loadConnectors}
      />
      <AvailableSources
        sources={sources.available}
        expandedId={sources.expandedId}
        loading={sources.loading}
        connectingId={sources.connectingId}
        connectStage={sources.connectStage}
        connectError={sources.connectError}
        onToggle={sources.setExpandedId}
        onConnect={sources.handleConnect}
        onRefresh={sources.loadConnectors}
      />
    </div>
  );
}
