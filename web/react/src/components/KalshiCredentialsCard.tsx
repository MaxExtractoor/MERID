/**
 * KalshiCredentialsCard - Settings component for Kalshi API credentials
 * 
 * Provides:
 * - Credential input fields (API Key ID, Private Key Path, Environment)
 * - Connection testing with classified error feedback
 * - Inline success/failure states with ErrorBar integration
 */

import React, { useState, useCallback } from 'react';
import { Icon } from '../ui/icons';
import { API_BASE_URL, API_ENDPOINTS } from '../config/constants';
import ErrorBar, { ClassifiedError } from '../components/ErrorBar';
import { classifyError } from '../utils/errorClassification';

interface KalshiCredentials {
  apiKeyId: string;
  privateKeyPath: string;
  environment: 'demo' | 'live';
}

interface ValidationState {
  lastValidated: string | null;
  validatedEnvironment: string | null;
  isValid: boolean;
  serverEnvironment: string | null;
}

const DEFAULT_CREDENTIALS: KalshiCredentials = {
  apiKeyId: '',
  privateKeyPath: '',
  environment: 'demo',
};

export default function KalshiCredentialsCard() {
  const [credentials, setCredentials] = useState<KalshiCredentials>(DEFAULT_CREDENTIALS);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<ClassifiedError | null>(null);
  const [savedCredentials, setSavedCredentials] = useState<KalshiCredentials | null>(null);
  const [validationState, setValidationState] = useState<ValidationState>({
    lastValidated: null,
    validatedEnvironment: null,
    isValid: false,
    serverEnvironment: null,
  });

  // Load credentials and validation state from sessionStorage on mount.
  // sessionStorage is scoped to the browser tab and cleared when it closes,
  // unlike localStorage which persists indefinitely.
  React.useEffect(() => {
    try {
      const saved = sessionStorage.getItem('merid:kalshi:credentials');
      if (saved) {
        const parsed = JSON.parse(saved);
        setSavedCredentials(parsed);
        setCredentials(parsed);
      }

      const validation = sessionStorage.getItem('merid:kalshi:validation');
      if (validation) {
        const parsed = JSON.parse(validation);
        setValidationState(parsed);
      }

      // Migrate any values that were previously persisted to localStorage
      const legacy = localStorage.getItem('merid:kalshi:credentials');
      if (legacy) {
        localStorage.removeItem('merid:kalshi:credentials');
        localStorage.removeItem('merid:kalshi:validation');
      }
    } catch (error) {
      console.warn('Failed to load saved Kalshi credentials:', error);
    }
  }, []);

  const handleInputChange = useCallback((field: keyof KalshiCredentials, value: string) => {
    setCredentials(prev => ({ ...prev, [field]: value }));
    setTestResult(null); // Clear previous test result
  }, []);

  const testConnection = useCallback(async () => {
    setTesting(true);
    setTestResult(null);

    try {
      // Test with a lightweight endpoint that requires authentication
      const response = await fetch(`${API_BASE_URL}${API_ENDPOINTS.KALSHI_HEALTH}`, {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
          'X-Kalshi-API-Key-ID': credentials.apiKeyId,
          'X-Kalshi-Environment': credentials.environment,
          // Note: In production, private key would be handled server-side
          // This is a simplified test for UI demonstration
        },
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        const error = new Error(errorData.message || `HTTP ${response.status}`);
        (error as any).status = response.status;
        (error as any).code = errorData.code;
        throw error;
      }

      const data = await response.json();
      
      // Update validation state with server response
      const newValidationState: ValidationState = {
        lastValidated: new Date().toISOString(),
        validatedEnvironment: credentials.environment,
        isValid: true,
        serverEnvironment: data.environment || credentials.environment,
      };
      
      // Store credentials in sessionStorage only (clears when browser tab closes)
      sessionStorage.setItem('merid:kalshi:credentials', JSON.stringify(credentials));
      sessionStorage.setItem('merid:kalshi:validation', JSON.stringify(newValidationState));
      setSavedCredentials(credentials);
      setValidationState(newValidationState);
      
      setTestResult({
        message: `Connection successful. Environment: ${data.environment || credentials.environment}`,
        class: 'network',
        action: 'Credentials verified and saved',
        retryable: false,
      });

    } catch (error) {
      const classified = classifyError(error as Error);
      setTestResult(classified);
      
      // Update validation state on failure
      const failedValidationState: ValidationState = {
        lastValidated: new Date().toISOString(),
        validatedEnvironment: credentials.environment,
        isValid: false,
        serverEnvironment: null,
      };
      setValidationState(failedValidationState);
      sessionStorage.setItem('merid:kalshi:validation', JSON.stringify(failedValidationState));
    } finally {
      setTesting(false);
    }
  }, [credentials]);

  const clearCredentials = useCallback(() => {
    sessionStorage.removeItem('merid:kalshi:credentials');
    sessionStorage.removeItem('merid:kalshi:validation');
    setCredentials(DEFAULT_CREDENTIALS);
    setSavedCredentials(null);
    setValidationState({
      lastValidated: null,
      validatedEnvironment: null,
      isValid: false,
      serverEnvironment: null,
    });
    setTestResult(null);
  }, []);

  const isFormValid = credentials.apiKeyId.trim() !== '' && credentials.privateKeyPath.trim() !== '';

  return (
    <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-6 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Icon name="shield" size={20} className="w-5 h-5 text-orange-400" />
          <div>
            <h3 className="text-lg font-semibold text-white">Kalshi Credentials</h3>
            <p className="text-sm text-gray-400">
              Configure API credentials for Kalshi trading
            </p>
          </div>
        </div>
        {savedCredentials && (
          <div className="flex items-center gap-2 text-xs text-green-400">
            <Icon name="check" size={14} className="w-3.5 h-3.5" />
            Configured
          </div>
        )}
      </div>

      {/* Credential Fields */}
      <div className="space-y-4">
        {/* API Key ID */}
        <div>
          <label className="block text-sm font-medium text-gray-300 mb-2">
            API Key ID
          </label>
          <input
            type="text"
            value={credentials.apiKeyId}
            onChange={(e) => handleInputChange('apiKeyId', e.target.value)}
            placeholder="e.g., kalshi_live_abc123..."
            className="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-lg text-sm text-white placeholder-gray-500 focus:border-orange-500 focus:outline-none"
            aria-label="Kalshi API Key ID"
          />
        </div>

        {/* Private Key Path */}
        <div>
          <label className="block text-sm font-medium text-gray-300 mb-2">
            Private Key Path
          </label>
          <input
            type="text"
            value={credentials.privateKeyPath}
            onChange={(e) => handleInputChange('privateKeyPath', e.target.value)}
            placeholder="/path/to/kalshi_private_key.pem"
            className="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-lg text-sm text-white placeholder-gray-500 focus:border-orange-500 focus:outline-none"
            aria-label="Private key file path"
          />
        </div>

        {/* Environment */}
        <div>
          <label className="block text-sm font-medium text-gray-300 mb-2">
            Environment
          </label>
          <select
            value={credentials.environment}
            onChange={(e) => handleInputChange('environment', e.target.value as 'demo' | 'live')}
            className="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-lg text-sm text-white focus:border-orange-500 focus:outline-none"
            aria-label="Kalshi environment"
          >
            <option value="demo">Demo (Sandbox)</option>
            <option value="live">Live (Production)</option>
          </select>
        </div>
      </div>

      {/* Test Result */}
      {testResult && (
        <ErrorBar
          label="Connection Test"
          error={testResult}
          onRetry={testResult.retryable ? testConnection : undefined}
        />
      )}

      {/* Environment Mismatch Warning */}
      {validationState.isValid && validationState.serverEnvironment && 
       validationState.serverEnvironment.toLowerCase() !== credentials.environment && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-400 text-sm">
          <Icon name="alert" size={16} className="w-4 h-4 shrink-0" />
          <span>
            Environment mismatch: Card set to {credentials.environment.toUpperCase()} but server validated as {validationState.serverEnvironment.toUpperCase()}
          </span>
        </div>
      )}

      {/* Validation Status */}
      {validationState.lastValidated && (
        <div className="text-xs text-gray-500">
          Last validated: {new Date(validationState.lastValidated).toLocaleString()}
          {validationState.isValid && validationState.validatedEnvironment && (
            <span className="ml-2">
              (env: {validationState.validatedEnvironment.toUpperCase()})
            </span>
          )}
        </div>
      )}

      {/* Actions */}
      <div className="flex items-center gap-3 pt-2">
        <button
          type="button"
          onClick={testConnection}
          disabled={!isFormValid || testing}
          className="flex items-center gap-2 px-4 py-2 bg-orange-500 hover:bg-orange-600 disabled:bg-slate-600 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
        >
          {testing ? (
            <>
              <Icon name="refresh" size={14} className="w-3.5 h-3.5 animate-spin" />
              Testing...
            </>
          ) : (
            <>
              <Icon name="wifi" size={14} className="w-3.5 h-3.5" />
              Test Connection
            </>
          )}
        </button>

        {savedCredentials && (
          <button
            type="button"
            onClick={clearCredentials}
            className="flex items-center gap-2 px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white text-sm font-medium rounded-lg transition-colors"
          >
            <Icon name="close" size={14} className="w-3.5 h-3.5" />
            Clear
          </button>
        )}

        <div className="ml-auto text-xs text-gray-500">
          {credentials.environment === 'live' && (
            <span className="flex items-center gap-1 text-red-400">
              <Icon name="alert" size={12} className="w-3 h-3" />
              Live environment
            </span>
          )}
        </div>
      </div>

      {/* Help Text */}
      <div className="text-xs text-gray-500 space-y-1">
        <p>• Credentials are stored for this browser session only and cleared on tab close</p>
        <p>• The private key never leaves the server — only the file path is stored here</p>
        <p>• For persistent config, set <code className="font-mono text-gray-400">KALSHI_*</code> env vars in your <code className="font-mono text-gray-400">.env</code> file</p>
        <p>• Use Demo environment for testing, Live for real trading</p>
      </div>
    </div>
  );
}
