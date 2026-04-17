import * as icons from '../ui/icons';

describe('icons barrel debug', () => {
  it('check all exports from ui/icons', () => {
    const undefs = Object.entries(icons).filter(([, v]) => v === undefined).map(([k]) => k);
    console.log('undefined exports:', undefs.length, JSON.stringify(undefs));
    console.log('total exports:', Object.keys(icons).length);
    console.log('TrendingUp:', typeof icons.TrendingUp);
    console.log('TrendingDown:', typeof icons.TrendingDown);
    console.log('Activity:', typeof icons.Activity);
    console.log('default:', typeof icons.default);
    expect(undefs.length).toBe(0);
  });
});
