import json
import urllib.request
import urllib.error
import time

class EventEmitter:
    def __init__(self, api_url: str = "http://localhost:8000/events/ingest"):
        self.api_url = api_url
        self.buffer = []

    def queue_event(self, event: dict):
        """
        Queues an event in the local buffer.
        """
        self.buffer.append(event)

    def emit_batch(self) -> bool:
        """
        Sends all queued events in the buffer to the ingest API.
        Enforces the 500 event maximum batch constraint.
        """
        if not self.buffer:
            print("Emitter: Buffer is empty. Nothing to emit.")
            return True

        print(f"Emitter: Preparing to emit {len(self.buffer)} events...")
        success = True

        # Process in batches of 500
        while self.buffer:
            batch = self.buffer[:500]
            self.buffer = self.buffer[500:]

            payload = json.dumps(batch).encode('utf-8')
            req = urllib.request.Request(
                self.api_url,
                data=payload,
                headers={'Content-Type': 'application/json'}
            )

            try:
                with urllib.request.urlopen(req) as response:
                    res_body = response.read().decode('utf-8')
                    res_json = json.loads(res_body)
                    print(f"Emitter Success: {res_json.get('processed', 0)} processed, {res_json.get('errors', 0)} duplicates/skipped.")
            except urllib.error.HTTPError as e:
                print(f"Emitter API Error ({e.code}): {e.read().decode('utf-8')}")
                success = False
            except urllib.error.URLError as e:
                print(f"Emitter Connection Failure: Cannot reach API at {self.api_url}. Is the server running? Reason: {e.reason}")
                success = False

        return success

    def emit_live_stream(self, delay_seconds: float = 0.1):
        """
        Emits events one-by-one or in micro-batches with a delay
        to simulate real-time feed processing for the live dashboard.
        """
        if not self.buffer:
            return

        print(f"Emitter: Streaming {len(self.buffer)} events in simulated real-time...")
        for event in self.buffer:
            payload = json.dumps([event]).encode('utf-8')
            req = urllib.request.Request(
                self.api_url,
                data=payload,
                headers={'Content-Type': 'application/json'}
            )
            try:
                with urllib.request.urlopen(req) as response:
                    pass
            except Exception:
                pass
            time.sleep(delay_seconds)
        
        self.buffer.clear()
        print("Emitter: Simulated streaming finished.")
