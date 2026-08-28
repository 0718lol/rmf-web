import Box from '@mui/material/Box';

export interface TrajectoryViewProps {
  url: string;
}

export function TrajectoryView({ url }: TrajectoryViewProps) {
  return (
    <Box sx={{ width: '100%', height: '100%', minHeight: 480, bgcolor: 'background.default' }}>
      <iframe
        title="RMF task trajectory observability"
        src={url}
        allow="clipboard-read; clipboard-write"
        referrerPolicy="no-referrer"
        sandbox="allow-downloads allow-forms allow-same-origin allow-scripts"
        style={{ width: '100%', height: '100%', minHeight: 480, display: 'block', border: 0 }}
      />
    </Box>
  );
}

export default TrajectoryView;
