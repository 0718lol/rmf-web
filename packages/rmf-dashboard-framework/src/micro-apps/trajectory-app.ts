import { createMicroApp, MicroAppManifest } from '../components';
import type { TrajectoryViewProps } from '../components/trajectory/trajectory-view';

export default function createTrajectoryApp(config: TrajectoryViewProps): MicroAppManifest {
  return createMicroApp(
    'trajectory-observability',
    'Trajectory',
    () => import('../components/trajectory/trajectory-view'),
    () => config,
  );
}
