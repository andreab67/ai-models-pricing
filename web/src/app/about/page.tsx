export default function AboutPage() {
  return (
    <div className="space-y-12">
      {/* Hero Section */}
      <section className="space-y-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight mb-2">AI Model Pricing Dashboard</h1>
          <p className="text-lg text-fg/80">
            Real-time cost tracking and optimization across 10+ LLM providers in one unified interface.
          </p>
        </div>
      </section>

      {/* Feature Cards */}
      <section className="grid md:grid-cols-3 gap-4">
        <div className="card rounded-lg p-6 space-y-3">
          <div className="text-2xl">📊</div>
          <h3 className="font-semibold">Multi-Provider Aggregation</h3>
          <p className="text-sm text-fg/70">
            Centralize pricing data from OpenRouter, OpenAI, Anthropic, and more into a single source of truth.
          </p>
        </div>
        <div className="card rounded-lg p-6 space-y-3">
          <div className="text-2xl">⚡</div>
          <h3 className="font-semibold">Real-Time Pricing</h3>
          <p className="text-sm text-fg/70">
            Automatic updates every 15 minutes normalize costs to USD per 1M tokens for instant comparison.
          </p>
        </div>
        <div className="card rounded-lg p-6 space-y-3">
          <div className="text-2xl">🎯</div>
          <h3 className="font-semibold">Intelligent Ranking</h3>
          <p className="text-sm text-fg/70">
            Data-driven model selection based on cost, context window, capability, and tool support.
          </p>
        </div>
      </section>

      {/* What It Does */}
      <section className="space-y-4">
        <h2 className="text-2xl font-bold">The Problem It Solves</h2>
        <p className="text-fg/80">
          Organizations using multiple LLM providers lack a unified view of costs and capabilities. Teams waste time:
        </p>
        <ul className="space-y-2 text-fg/70">
          <li className="flex gap-3">
            <span>❌</span>
            <span>Maintaining spreadsheets manually as prices change</span>
          </li>
          <li className="flex gap-3">
            <span>❌</span>
            <span>Missing hidden costs in tiering, credits, and discounts</span>
          </li>
          <li className="flex gap-3">
            <span>❌</span>
            <span>Making model selection decisions without real-time price data</span>
          </li>
          <li className="flex gap-3">
            <span>❌</span>
            <span>Tracking spending across provider dashboards separately</span>
          </li>
        </ul>
      </section>

      {/* Technical Stack */}
      <section className="space-y-4">
        <h2 className="text-2xl font-bold">Technical Architecture</h2>
        <p className="text-fg/80 mb-4">
          Production-ready full-stack implementation demonstrating modern AI infrastructure patterns:
        </p>
        <div className="grid md:grid-cols-2 gap-6">
          <div className="space-y-3">
            <h3 className="font-semibold flex items-center gap-2">
              <span>🔧</span> Backend
            </h3>
            <ul className="space-y-1 text-sm text-fg/70 ml-7">
              <li>• FastAPI with async/await for high concurrency</li>
              <li>• SQLAlchemy 2 ORM with Postgres for data persistence</li>
              <li>• Redis for intelligent caching (900s TTL)</li>
              <li>• Tenacity for resilient API retries</li>
            </ul>
          </div>
          <div className="space-y-3">
            <h3 className="font-semibold flex items-center gap-2">
              <span>🎨</span> Frontend
            </h3>
            <ul className="space-y-1 text-sm text-fg/70 ml-7">
              <li>• Next.js 14 App Router with React Server Components</li>
              <li>• Tailwind CSS + design tokens for consistency</li>
              <li>• Recharts for real-time data visualization</li>
              <li>• Dark/light mode with system preference detection</li>
            </ul>
          </div>
          <div className="space-y-3">
            <h3 className="font-semibold flex items-center gap-2">
              <span>☸️</span> Infrastructure
            </h3>
            <ul className="space-y-1 text-sm text-fg/70 ml-7">
              <li>• Kubernetes for orchestration and scaling</li>
              <li>• CronJobs for automated pricing refresh & reporting</li>
              <li>• Traefik ingress with cert-manager TLS</li>
              <li>• Prometheus metrics and structured logging</li>
            </ul>
          </div>
          <div className="space-y-3">
            <h3 className="font-semibold flex items-center gap-2">
              <span>🔗</span> Integration
            </h3>
            <ul className="space-y-1 text-sm text-fg/70 ml-7">
              <li>• Concurrent API calls with fallback strategies</li>
              <li>• Normalized cost calculations across providers</li>
              <li>• Real-time account balance & activity tracking</li>
              <li>• Error boundaries and graceful degradation</li>
            </ul>
          </div>
        </div>
      </section>

      {/* Why This Matters */}
      <section className="space-y-4">
        <h2 className="text-2xl font-bold">Expertise Demonstrated</h2>
        <ul className="space-y-3">
          <li className="flex gap-3">
            <span className="text-accent font-bold">✓</span>
            <div>
              <p className="font-semibold">AI Operations & Cost Optimization</p>
              <p className="text-sm text-fg/70">Deep understanding of LLM economics, pricing models, and cost analysis</p>
            </div>
          </li>
          <li className="flex gap-3">
            <span className="text-accent font-bold">✓</span>
            <div>
              <p className="font-semibold">Full-Stack Development</p>
              <p className="text-sm text-fg/70">Modern Python backend, React frontend, Kubernetes infrastructure, all production-ready</p>
            </div>
          </li>
          <li className="flex gap-3">
            <span className="text-accent font-bold">✓</span>
            <div>
              <p className="font-semibold">Data Pipeline Architecture</p>
              <p className="text-sm text-fg/70">Real-time data ingestion, normalization, caching, and persistence at scale</p>
            </div>
          </li>
          <li className="flex gap-3">
            <span className="text-accent font-bold">✓</span>
            <div>
              <p className="font-semibold">Multi-Provider Integration</p>
              <p className="text-sm text-fg/70">Orchestrating APIs from competing providers with concurrent calls and error handling</p>
            </div>
          </li>
        </ul>
      </section>

      {/* CTA Section */}
      <section className="bg-accent/10 rounded-lg p-8 space-y-4 text-center">
        <h2 className="text-2xl font-bold">Available for C2C Consulting</h2>
        <p className="text-fg/80 max-w-2xl mx-auto">
          If you need similar infrastructure for your organization—custom cost tracking dashboards, multi-provider orchestration,
          or operational tools for AI systems—this project demonstrates the technical depth available.
        </p>
        <p className="text-sm text-fg/70">
          <strong>Services:</strong> Full-stack AI systems · Cost optimization tools · LLM infrastructure · Real-time dashboards · Multi-provider integration
        </p>
        <div className="flex gap-3 justify-center pt-4">
          <a
            href="https://www.greenyogainc.com/book"
            className="px-6 py-2 bg-accent text-accent-foreground rounded-lg font-semibold hover:opacity-90 transition"
          >
            Get in Touch
          </a>
        </div>
      </section>
    </div>
  );
}
