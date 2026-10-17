export interface User {
  id: number;
  email: string;
  created_at: string;
}

export interface Dashboard {
  message: string;
  user: User;
}

export interface Site {
  id: number;
  name: string;
  url: string;
  currency: string;
  is_demo: boolean;
}

export interface Product {
  id: number;
  site_id: number;
  name: string;
  sku: string;
  category: string;
  unit_price: string;
}

export interface DailySales {
  date: string;
  revenue: number;
  orders: number;
  units_sold: number;
}

export interface ProductSales {
  product_id: number;
  name: string;
  sku: string;
  revenue: number;
  orders: number;
  units_sold: number;
}

export interface AnalyticsOverview {
  start_date: string;
  end_date: string;
  currency: string;
  revenue: number;
  orders: number;
  units_sold: number;
  average_order_value: number;
  daily_sales: DailySales[];
  product_sales: ProductSales[];
}

export interface ChatConversation {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface ChatMessage {
  id: number;
  request_id: string;
  role: "user" | "assistant";
  content: string;
  metadata_json: Record<string, unknown> | null;
  created_at: string;
}

export interface ChatFilters {
  site_id: number | null;
  product_id: number | null;
  start_date: string;
  end_date: string;
}

export interface ChatSocketEvent {
  type: "assistant.delta" | "assistant.done" | "error";
  request_id: string;
  content?: string;
  code?: string;
  message?: string;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "";

export function websocketUrl(path: string): string {
  const url = new URL(apiBaseUrl || window.location.origin, window.location.origin);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = path;
  url.search = "";
  return url.toString();
}

export async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  let response: Response;
  try {
    const headers = new Headers(options.headers);
    if (options.body && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    response = await fetch(`${apiBaseUrl}${path}`, {
      ...options,
      credentials: "include",
      headers,
    });
  } catch {
    throw new ApiError("Unable to connect to the server.", 0);
  }

  if (!response.ok) {
    let message = "The request could not be completed.";
    try {
      const body: unknown = await response.json();
      if (
        typeof body === "object" &&
        body !== null &&
        "detail" in body &&
        typeof body.detail === "string"
      ) {
        message = body.detail;
      }
    } catch {
      // Keep the generic API error when the response has no JSON body.
    }
    throw new ApiError(message, response.status);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}
