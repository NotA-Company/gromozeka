"""Simple test demonstrating the golden data infrastructure functionality.

This test shows how to use the recording and replaying functionality
with a simple httpx client making recordings to httpbin.org.
"""

import asyncio

import httpx

from .recorder import GoldenDataRecorder
from .replayer import GoldenDataReplayer


async def makeTestCalls(client: httpx.AsyncClient):
    """Make some test HTTP recordings.

    Args:
        client: httpx.AsyncClient to use for making recordings
    """
    # Make a GET request
    response1 = await client.get("https://httpbin.org/get")
    print(f"GET status: {response1.status_code}")

    # Make a POST request with JSON data
    data = {"key": "value", "test": "data"}
    response2 = await client.post("https://httpbin.org/post", json=data)
    print(f"POST status: {response2.status_code}")

    # Make a GET request with query parameters
    params = {"param1": "value1", "param2": "value2"}
    response3 = await client.get("https://httpbin.org/get", params=params)
    print(f"GET with params status: {response3.status_code}")


async def testRecording():
    """Test the recording functionality."""
    print("=== Testing Recording ===")

    # Create recorder with some secrets to mask
    secrets = ["secret123", "token456"]
    recorder = GoldenDataRecorder(secrets=secrets)

    # Use recorder as context manager for global patching
    async with recorder:
        # Create a regular httpx client - it will use our patched transport
        client = httpx.AsyncClient()

        try:
            # Make test recordings
            await makeTestCalls(client)

            # Get recorded recordings
            recordings = recorder.getRecordedRecordings()
            print(f"Recorded {len(recordings)} recordings")

            # Create scenario
            scenario = recorder.createScenario(
                description="Test HTTP recordings to httpbin.org",
                module="test_infrastructure",
                className="test_recording",
                method="makeTestCalls",
                kwargs={},
            )

            print(f"Created scenario with {len(scenario['recordings'])} recordings")
            print(f"Scenario created at: {scenario['createdAt']}")

            return scenario
        finally:
            await client.aclose()


async def test_replaying(scenario):
    """Test the replaying functionality.

    Args:
        scenario: GoldenDataScenarioDict to replay
    """
    print("\n=== Testing Replaying ===")

    # Create replayer with scenario
    replayer = GoldenDataReplayer(scenario)

    # Create client with replay transport
    client = replayer.createClient()

    try:
        # Make the same recordings (they should be replayed)
        await makeTestCalls(client)

        # Verify all recordings were used
        all_used = replayer.verifyAllCallsUsed()
        print(f"All recordings used: {all_used}")

    except Exception as e:
        print(f"Error during replay: {e}")
    finally:
        await client.aclose()


async def main():
    """Main test function."""
    print("Testing Golden Data Infrastructure")
    print("=" * 40)

    # Test recording
    scenario = await testRecording()

    # Test replaying
    await test_replaying(scenario)

    print("\n=== Test Complete ===")


if __name__ == "__main__":
    asyncio.run(main())
