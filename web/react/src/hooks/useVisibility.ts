import { useState, useEffect } from 'react';

/**
 * useVisibility - Detects when the browser tab is visible vs hidden
 * Used for intelligent polling (Tier 1 optimization)
 * 
 * Returns:
 * - isVisible: true if tab is visible, false if hidden
 * 
 * Usage:
 * const isVisible = useVisibility();
 * if (!isVisible) return; // Skip expensive operations when tab is hidden
 */
export function useVisibility(): boolean {
  const [isVisible, setIsVisible] = useState(true);

  useEffect(() => {
    // Handle visibility change
    const handleVisibilityChange = () => {
      setIsVisible(!document.hidden);
    };

    // Add event listener
    document.addEventListener('visibilitychange', handleVisibilityChange);

    // Initial check
    setIsVisible(!document.hidden);

    // Cleanup
    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, []);

  return isVisible;
}
