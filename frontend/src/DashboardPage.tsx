import { useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  ApiError,
  request,
  type AnalyticsOverview,
  type Product,
  type Site,
} from "./api";
import { useAuth } from "./auth";
import { ChatPanel } from "./ChatPanel";

function toIsoDate(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function defaultStartDate(): string {
  const date = new Date();
  date.setDate(date.getDate() - 29);
  return toIsoDate(date);
}

function formatCurrency(value: number, currency: string): string {
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(value);
}

function formatChartDate(value: string): string {
  return new Date(`${value}T00:00:00`).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

export function DashboardPage() {
  const { state, signOut } = useAuth();
  const [sites, setSites] = useState<Site[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [overview, setOverview] = useState<AnalyticsOverview | null>(null);
  const [siteId, setSiteId] = useState("");
  const [productId, setProductId] = useState("");
  const [startDate, setStartDate] = useState(defaultStartDate);
  const [endDate, setEndDate] = useState(() => toIsoDate(new Date()));
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [signingOut, setSigningOut] = useState(false);

  const visibleProducts = useMemo(
    () =>
      siteId
        ? products.filter((product) => product.site_id === Number(siteId))
        : products,
    [products, siteId],
  );

  useEffect(() => {
    let active = true;
    Promise.all([
      request<Site[]>("/api/analytics/sites"),
      request<Product[]>("/api/analytics/products"),
    ])
      .then(([siteResults, productResults]) => {
        if (!active) return;
        setSites(siteResults);
        setProducts(productResults);
      })
      .catch((requestError: unknown) => {
        if (active) {
          setError(
            requestError instanceof ApiError
              ? requestError.message
              : "Unable to load your sites and products.",
          );
          setLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (startDate > endDate) {
      setError("Start date must be on or before end date.");
      setLoading(false);
      return;
    }

    let active = true;
    const params = new URLSearchParams({
      start_date: startDate,
      end_date: endDate,
    });
    if (siteId) params.set("site_id", siteId);
    if (productId) params.set("product_id", productId);

    setLoading(true);
    setError("");
    request<AnalyticsOverview>(`/api/analytics/overview?${params.toString()}`)
      .then((data) => {
        if (active) setOverview(data);
      })
      .catch((requestError: unknown) => {
        if (active) {
          setError(
            requestError instanceof ApiError
              ? requestError.message
              : "Unable to load sales analytics.",
          );
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [startDate, endDate, siteId, productId]);

  async function handleSignOut() {
    setSigningOut(true);
    setError("");
    try {
      await signOut();
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Unable to sign out. Please try again.",
      );
      setSigningOut(false);
    }
  }

  if (state.status !== "authenticated") return null;
  const currency = overview?.currency ?? "USD";

  return (
    <main className="dashboard-layout">
      <header className="dashboard-header">
        <a className="wordmark" href="/">
          <span className="brand-mark brand-mark-small" aria-hidden="true">
            MI
          </span>
          Marketing Intelligence Copilot
        </a>
        <div className="account-actions">
          <span className="account-email">{state.user.email}</span>
          <button
            className="button button-secondary"
            onClick={() => void handleSignOut()}
            disabled={signingOut}
          >
            {signingOut ? "Signing out…" : "Sign out"}
          </button>
        </div>
      </header>

      <section className="analytics-heading">
        <div>
          <p className="eyebrow">YOUR WORKSPACE · DEMO DATA</p>
          <h1>Sales overview</h1>
          <p className="subtitle">
            Track sales performance across your example storefronts.
          </p>
        </div>
        <div className="date-range">
          <label>
            <span>From</span>
            <input
              aria-label="Start date"
              type="date"
              value={startDate}
              max={endDate}
              onChange={(event) => setStartDate(event.target.value)}
            />
          </label>
          <label>
            <span>To</span>
            <input
              aria-label="End date"
              type="date"
              value={endDate}
              min={startDate}
              onChange={(event) => setEndDate(event.target.value)}
            />
          </label>
        </div>
      </section>

      <section className="filter-bar" aria-label="Sales filters">
        <label>
          <span>Website</span>
          <select
            value={siteId}
            onChange={(event) => {
              setSiteId(event.target.value);
              setProductId("");
            }}
          >
            <option value="">All websites</option>
            {sites.map((site) => (
              <option key={site.id} value={site.id}>
                {site.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Product</span>
          <select
            value={productId}
            onChange={(event) => setProductId(event.target.value)}
          >
            <option value="">All products</option>
            {visibleProducts.map((product) => (
              <option key={product.id} value={product.id}>
                {product.name}
              </option>
            ))}
          </select>
        </label>
        <span className="data-note">Sample data · Updated from PostgreSQL</span>
      </section>

      {error && (
        <p className="form-error dashboard-error" role="alert">
          {error}
        </p>
      )}
      {loading && <p className="loading-note">Loading sales data…</p>}

      {overview && !error && (
        <>
          <section className="metric-grid" aria-label="Sales metrics">
            <article className="metric-card">
              <p>Net revenue</p>
              <strong>{formatCurrency(overview.revenue, currency)}</strong>
              <span>After discounts</span>
            </article>
            <article className="metric-card">
              <p>Orders</p>
              <strong>{overview.orders.toLocaleString()}</strong>
              <span>Distinct orders</span>
            </article>
            <article className="metric-card">
              <p>Units sold</p>
              <strong>{overview.units_sold.toLocaleString()}</strong>
              <span>Across selected products</span>
            </article>
            <article className="metric-card">
              <p>Average order value</p>
              <strong>
                {formatCurrency(overview.average_order_value, currency)}
              </strong>
              <span>Net revenue per order</span>
            </article>
          </section>

          {overview.orders === 0 ? (
            <section className="chart-card empty-state">
              <h2>No sales in this date range</h2>
              <p>Try a wider date range or choose a different website.</p>
            </section>
          ) : (
            <section className="chart-grid">
              <article className="chart-card sales-chart-card">
                <div className="chart-heading">
                  <div>
                    <h2>Revenue over time</h2>
                    <p>Daily net sales · {currency}</p>
                  </div>
                </div>
                <div className="chart-wrap">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart
                      data={overview.daily_sales}
                      margin={{ top: 12, right: 18, left: 4, bottom: 4 }}
                      accessibilityLayer
                    >
                      <CartesianGrid stroke="#edf0f5" vertical={false} />
                      <XAxis
                        dataKey="date"
                        tickFormatter={formatChartDate}
                        minTickGap={28}
                        tickLine={false}
                        axisLine={false}
                        tick={{ fill: "#858da0", fontSize: 11 }}
                      />
                      <YAxis
                        tickFormatter={(value: number) =>
                          new Intl.NumberFormat(undefined, {
                            notation: "compact",
                            maximumFractionDigits: 1,
                          }).format(value)
                        }
                        tickLine={false}
                        axisLine={false}
                        width={48}
                        tick={{ fill: "#858da0", fontSize: 11 }}
                      />
                      <Tooltip
                        labelFormatter={(label) => formatChartDate(String(label))}
                        formatter={(value) => [
                          formatCurrency(Number(value), currency),
                          "Net revenue",
                        ]}
                        contentStyle={{
                          border: "1px solid #e8eaf0",
                          borderRadius: 10,
                          boxShadow: "0 8px 24px rgb(34 48 87 / 10%)",
                        }}
                      />
                      <Line
                        type="monotone"
                        dataKey="revenue"
                        name="Net revenue"
                        stroke="#4b65be"
                        strokeWidth={2.5}
                        dot={false}
                        activeDot={{ r: 5, fill: "#4b65be" }}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
                <p className="chart-accessible-summary">
                  Sales revenue line chart for {overview.daily_sales.length} days.
                  Total net revenue is {formatCurrency(overview.revenue, currency)}.
                </p>
              </article>

              <article className="chart-card product-chart-card">
                <div className="chart-heading">
                  <div>
                    <h2>Sales by product</h2>
                    <p>Top products by net revenue</p>
                  </div>
                </div>
                <div className="chart-wrap">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart
                      data={overview.product_sales.slice(0, 6)}
                      layout="vertical"
                      margin={{ top: 8, right: 16, left: 6, bottom: 4 }}
                      accessibilityLayer
                    >
                      <CartesianGrid stroke="#edf0f5" horizontal={false} />
                      <XAxis
                        type="number"
                        tickFormatter={(value: number) =>
                          new Intl.NumberFormat(undefined, {
                            notation: "compact",
                            maximumFractionDigits: 1,
                          }).format(value)
                        }
                        tickLine={false}
                        axisLine={false}
                        tick={{ fill: "#858da0", fontSize: 11 }}
                      />
                      <YAxis
                        type="category"
                        dataKey="name"
                        width={126}
                        tickLine={false}
                        axisLine={false}
                        tick={{ fill: "#60697b", fontSize: 11 }}
                      />
                      <Tooltip
                        formatter={(value) => [
                          formatCurrency(Number(value), currency),
                          "Net revenue",
                        ]}
                        contentStyle={{
                          border: "1px solid #e8eaf0",
                          borderRadius: 10,
                          boxShadow: "0 8px 24px rgb(34 48 87 / 10%)",
                        }}
                      />
                      <Legend />
                      <Bar
                        dataKey="revenue"
                        name="Net revenue"
                        fill="#53a894"
                        radius={[0, 5, 5, 0]}
                        maxBarSize={22}
                      />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
                <p className="chart-accessible-summary">
                  Product revenue bar chart showing {overview.product_sales.length} products.
                </p>
              </article>
            </section>
          )}
        </>
      )}

      <ChatPanel
        filters={{
          site_id: siteId ? Number(siteId) : null,
          product_id: productId ? Number(productId) : null,
          start_date: startDate,
          end_date: endDate,
        }}
      />
    </main>
  );
}
