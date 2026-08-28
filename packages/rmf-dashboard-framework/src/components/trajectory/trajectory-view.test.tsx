import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { TrajectoryView } from './trajectory-view';

describe('TrajectoryView', () => {
  it('loads the configured observability URL in an isolated iframe', () => {
    const root = render(<TrajectoryView url="http://localhost:8080" />);
    const frame = root.getByTitle('RMF task trajectory observability');

    expect(frame.getAttribute('src')).toBe('http://localhost:8080');
    expect(frame.getAttribute('sandbox')).toContain('allow-scripts');
  });
});
