import { TrendingUp, TrendingDown, Activity, X } from 'lucide-react';

describe('lucide-react mock debug', () => {
  it('TrendingUp is defined', () => {
    console.log('TrendingUp type:', typeof TrendingUp);
    console.log('TrendingDown type:', typeof TrendingDown);
    console.log('Activity type:', typeof Activity);
    console.log('X type:', typeof X);
    expect(TrendingUp).toBeDefined();
  });
});
