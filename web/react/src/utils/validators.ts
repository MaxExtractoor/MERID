// Form validation utilities for MERID dashboard

export interface ValidationResult {
  valid: boolean;
  error?: string;
  errors?: string[];
  message?: string;
}

export function validateSymbol(symbol: string | null | undefined): ValidationResult {
  if (!symbol || symbol.trim().length === 0) {
    return { valid: false, error: "Symbol is required" };
  }

  const cleanSymbol = symbol.trim().toUpperCase();
  
  // Check for valid symbol format (e.g., BTC-USD, ETH-USD, BTC/USD, BTCUSD)
  if (!/^[A-Z]{2,6}[/-]?[A-Z]{3,4}$/.test(cleanSymbol)) {
    return { valid: false, error: "Invalid symbol format" };
  }

  return { valid: true };
}

interface SizeOptions {
  minSize?: number;
  maxSize?: number;
}

export function validateSize(size: string | number, options?: number | SizeOptions): ValidationResult {
  const numSize = typeof size === "string" ? parseFloat(size) : size;

  if (isNaN(numSize)) {
    return { valid: false, error: "Size must be a valid number" };
  }

  if (numSize <= 0) {
    return { valid: false, error: "Size must be greater than 0" };
  }

  // Handle options as number (maxSize) or object
  let maxSize: number | undefined;
  let minSize: number | undefined;
  
  if (typeof options === 'number') {
    maxSize = options;
  } else if (options) {
    maxSize = options.maxSize;
    minSize = options.minSize;
  }

  if (minSize !== undefined && numSize < minSize) {
    return { valid: false, error: `Minimum size is ${minSize}` };
  }

  if (maxSize !== undefined && numSize > maxSize) {
    return { valid: false, error: `Maximum size is ${maxSize}` };
  }

  return { valid: true };
}

interface PriceOptions {
  maxPrecision?: number;
}

export function validatePrice(price: string | number, options?: PriceOptions): ValidationResult {
  const numPrice = typeof price === "string" ? parseFloat(price) : price;

  if (isNaN(numPrice)) {
    return { valid: false, error: "Price must be a valid number" };
  }

  if (numPrice <= 0) {
    return { valid: false, error: "Price must be greater than 0" };
  }

  // Check precision if specified
  if (options?.maxPrecision !== undefined) {
    const decimalPlaces = (numPrice.toString().split(".")[1] || "").length;
    if (decimalPlaces > options.maxPrecision) {
      return { valid: false, error: `Price precision too high (max ${options.maxPrecision} decimal places)` };
    }
  }

  return { valid: true };
}

interface LeverageOptions {
  maxLeverage?: number;
}

export function validateLeverage(leverage: string | number, options?: number | LeverageOptions): ValidationResult {
  const numLeverage = typeof leverage === "string" ? parseFloat(leverage) : leverage;

  if (isNaN(numLeverage)) {
    return { valid: false, error: "Leverage must be a valid number" };
  }

  if (numLeverage < 1) {
    return { valid: false, error: "Leverage must be at least 1" };
  }

  // Handle options as number or object
  let maxLeverage: number | undefined;
  
  if (typeof options === 'number') {
    maxLeverage = options;
  } else if (options) {
    maxLeverage = options.maxLeverage;
  }

  if (maxLeverage !== undefined && numLeverage > maxLeverage) {
    return { valid: false, error: `Maximum leverage is ${maxLeverage}` };
  }

  return { valid: true };
}

export function validateOrderType(orderType: string): ValidationResult {
  if (!orderType || orderType.trim().length === 0) {
    return { valid: false, error: "Order type is required" };
  }

  const validTypes = ["MARKET", "LIMIT", "STOP", "STOP_LIMIT", "BRACKET"];
  const cleanType = orderType.trim().toUpperCase().replace('-', '_');

  if (!validTypes.includes(cleanType)) {
    return { valid: false, error: "Invalid order type" };
  }

  return { valid: true };
}

export function validateSide(side: string): ValidationResult {
  if (!side || side.trim().length === 0) {
    return { valid: false, error: "Order side is required" };
  }

  const validSides = ["BUY", "SELL"];
  const cleanSide = side.trim().toUpperCase();

  if (!validSides.includes(cleanSide)) {
    return { valid: false, error: "Order side must be buy or sell" };
  }

  return { valid: true };
}

// Alias for backward compatibility
export { validateSide as validateOrderSide };

interface VenueOptions {
  venues?: string[];
}

export function validateVenue(venue: string, options?: VenueOptions): ValidationResult {
  if (!venue || venue.trim().length === 0) {
    return { valid: false, error: "Venue is required" };
  }

  const cleanVenue = venue.trim().toUpperCase();
  
  // Use custom venues if provided, otherwise default to KALSHI only
  const validVenues = options?.venues?.map(v => v.toUpperCase()) ||
    ["KALSHI"];

  if (!validVenues.includes(cleanVenue)) {
    return { valid: false, error: "Invalid venue" };
  }

  return { valid: true };
}

export function validateEmail(email: string): ValidationResult {
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  
  if (!email || email.trim().length === 0) {
    return { valid: false, error: "Email is required" };
  }

  if (!emailRegex.test(email.trim())) {
    return { valid: false, error: "Invalid email format" };
  }

  return { valid: true };
}

interface PasswordOptions {
  minLength?: number;
}

export function validatePassword(password: string, options?: PasswordOptions): ValidationResult {
  if (!password || password.length === 0) {
    return { valid: false, error: "Password is required" };
  }

  const minLength = options?.minLength ?? 8;

  if (password.length < minLength) {
    return { valid: false, error: `Password must be at least ${minLength} characters` };
  }

  // Only check complexity requirements if no custom options provided
  // When options are provided, only apply the specified validations
  if (!options) {
    if (!/(?=.*[a-z])/.test(password)) {
      return { valid: false, error: "Password must contain at least one lowercase letter" };
    }

    if (!/(?=.*[A-Z])/.test(password)) {
      return { valid: false, error: "Password must contain at least one uppercase letter" };
    }

    if (!/(?=.*\d)/.test(password)) {
      return { valid: false, error: "Password must contain at least one number" };
    }

    if (!/(?=.*[!@#$%^&*()_+\-=[\]{};':"\\|,.<>/?])/.test(password)) {
      return { valid: false, error: "Password must contain at least one special character" };
    }
  }

  return { valid: true };
}

export function validateRequired(value: string, fieldName: string): ValidationResult {
  if (!value || value.trim().length === 0) {
    return { valid: false, message: `${fieldName} is required` };
  }

  return { valid: true };
}

export function validateNumberRange(
  value: string | number,
  min: number,
  max: number,
  fieldName: string
): ValidationResult {
  const numValue = typeof value === "string" ? parseFloat(value) : value;

  if (isNaN(numValue)) {
    return { valid: false, message: `${fieldName} must be a number` };
  }

  if (numValue < min || numValue > max) {
    return { valid: false, message: `${fieldName} must be between ${min} and ${max}` };
  }

  return { valid: true };
}

interface OrderTicketOptions {
  maxSize?: number;
}

export function validateOrderTicket(order: {
  symbol: string;
  side: string;
  orderType: string;
  size: string | number;
  price?: string | number;
  venue: string;
}, options?: OrderTicketOptions): ValidationResult {
  const errors: string[] = [];

  const symbolResult = validateSymbol(order.symbol);
  if (!symbolResult.valid) errors.push(symbolResult.error || "Invalid symbol");

  const sideResult = validateSide(order.side);
  if (!sideResult.valid) errors.push(sideResult.error || "Invalid side");

  const typeResult = validateOrderType(order.orderType);
  if (!typeResult.valid) errors.push(typeResult.error || "Invalid order type");

  const sizeOptions = options?.maxSize !== undefined ? { maxSize: options.maxSize } : undefined;
  const sizeResult = validateSize(order.size, sizeOptions);
  if (!sizeResult.valid) errors.push(sizeResult.error || "Invalid size");

  const venueResult = validateVenue(order.venue);
  if (!venueResult.valid) errors.push(venueResult.error || "Invalid venue");

  // Price is required for non-market orders
  if (order.orderType?.toUpperCase() !== "MARKET") {
    if (order.price === undefined) {
      errors.push("Price is required for limit orders");
    } else {
      const priceResult = validatePrice(order.price);
      if (!priceResult.valid) errors.push(priceResult.error || "Invalid price");
    }
  }

  if (errors.length > 0) {
    return { valid: false, errors };
  }

  return { valid: true };
}
