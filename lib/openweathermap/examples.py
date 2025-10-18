"""
OpenWeatherMap Client Usage Examples

This module demonstrates various ways to use the OpenWeatherMap client library
in the Gromozeka project.
"""

import asyncio
import logging
from typing import Optional

# Add project root to path for imports
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from lib.openweathermap import OpenWeatherMapClient, DictWeatherCache
from internal.config.manager import ConfigManager

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def basic_usage_example():
    """
    Basic usage example showing how to get weather for a city
    """
    print("=== Basic Usage Example ===")
    
    # Initialize database and cache
    cache = DictWeatherCache()
    
    # Create client with test configuration
    async with OpenWeatherMapClient(
        apiKey="your_api_key_here",  # Replace with real API key
        cache=cache,
        geocodingTTL=2592000,  # 30 days
        weatherTTL=1800,       # 30 minutes
        defaultLanguage="ru"
    ) as client:
        
        # Get weather for Moscow
        result = await client.getWeatherByCity("Moscow", "RU")
        
        if result:
            location = result['location']
            weather = result['weather']
            current = weather['current']
            
            print(f"🌍 Location: {location['name']}, {location['country']}")
            if 'ru' in location['local_names']:
                print(f"   Russian name: {location['local_names']['ru']}")
            
            print(f"🌡️  Temperature: {current['temp']}°C (feels like {current['feels_like']}°C)")
            print(f"☁️  Cloudiness: {current['clouds']}%")
            print(f"💨 Wind: {current['wind_speed']} m/s")
            print(f"💧 Humidity: {current['humidity']}%")
            print(f"📊 Pressure: {current['pressure']} hPa")
            print(f"🌤️  Description: {current['weather_description']}")
            
            # Show daily forecast
            if weather['daily']:
                print("\n📅 Daily Forecast:")
                for i, day in enumerate(weather['daily'][:3]):  # Show first 3 days
                    from datetime import datetime
                    date = datetime.fromtimestamp(day['dt']).strftime('%Y-%m-%d')
                    print(f"   {date}: {day['temp_min']}°C - {day['temp_max']}°C, {day['weather_description']}")
        else:
            print("❌ Failed to get weather data")

async def step_by_step_example():
    """
    Step-by-step example showing separate geocoding and weather calls
    """
    print("\n=== Step-by-Step Example ===")
    
    cache = DictWeatherCache()
    
    async with OpenWeatherMapClient(
        apiKey="your_api_key_here",
        cache=cache
    ) as client:
        
        # Step 1: Get coordinates for a city
        print("Step 1: Getting coordinates for London...")
        location = await client.getCoordinates("London", "GB")
        
        if location:
            print(f"✅ Found: {location['name']} at {location['lat']}, {location['lon']}")
            
            # Step 2: Get weather for those coordinates
            print("Step 2: Getting weather data...")
            weather = await client.getWeather(location['lat'], location['lon'])
            
            if weather:
                print(f"✅ Current temperature: {weather['current']['temp']}°C")
                print(f"   Weather: {weather['current']['weather_description']}")
            else:
                print("❌ Failed to get weather data")
        else:
            print("❌ Failed to get coordinates")

async def multiple_cities_example():
    """
    Example showing how to get weather for multiple cities
    """
    print("\n=== Multiple Cities Example ===")
    
    cities = [
        ("Moscow", "RU"),
        ("London", "GB"),
        ("New York", "US"),
        ("Tokyo", "JP"),
        ("Sydney", "AU")
    ]
    
    cache = DictWeatherCache()
    
    async with OpenWeatherMapClient(
        apiKey="your_api_key_here",
        cache=cache
    ) as client:
        
        print("🌍 Weather around the world:")
        
        for city, country in cities:
            result = await client.getWeatherByCity(city, country)
            
            if result:
                location = result['location']
                current = result['weather']['current']
                
                # Get local name if available
                local_name = location['local_names'].get('ru', location['name'])
                
                print(f"   {local_name} ({location['country']}): {current['temp']}°C, {current['weather_description']}")
            else:
                print(f"   {city} ({country}): ❌ Failed to get data")
            
            # Small delay to be nice to the API
            await asyncio.sleep(0.1)

async def cache_demonstration():
    """
    Example demonstrating cache behavior
    """
    print("\n=== Cache Demonstration ===")
    
    cache = DictWeatherCache()
    
    async with OpenWeatherMapClient(
        apiKey="your_api_key_here",
        cache=cache,
        weatherTTL=60  # Short TTL for demonstration
    ) as client:
        
        city = "Paris"
        country = "FR"
        
        print(f"First request for {city}...")
        start_time = asyncio.get_event_loop().time()
        result1 = await client.getWeatherByCity(city, country)
        first_duration = asyncio.get_event_loop().time() - start_time
        
        if result1:
            print(f"✅ Got weather data in {first_duration:.2f}s (API call)")
            temp1 = result1['weather']['current']['temp']
            print(f"   Temperature: {temp1}°C")
        
        print(f"\nSecond request for {city} (should use cache)...")
        start_time = asyncio.get_event_loop().time()
        result2 = await client.getWeatherByCity(city, country)
        second_duration = asyncio.get_event_loop().time() - start_time
        
        if result2:
            print(f"✅ Got weather data in {second_duration:.2f}s (cached)")
            temp2 = result2['weather']['current']['temp']
            print(f"   Temperature: {temp2}°C")
            
            if second_duration < first_duration:
                print("🚀 Cache made the second request faster!")

async def error_handling_example():
    """
    Example showing error handling
    """
    print("\n=== Error Handling Example ===")
    
    cache = DictWeatherCache()
    
    async with OpenWeatherMapClient(
        apiKey="invalid_key",  # Invalid API key
        cache=cache
    ) as client:
        
        # Try to get weather for a non-existent city
        print("Trying non-existent city...")
        result = await client.getWeatherByCity("NonexistentCity12345")
        
        if result is None:
            print("✅ Properly handled non-existent city")
        
        # Try with invalid API key (would fail in real usage)
        print("Note: Invalid API key would be handled gracefully")
        print("The client logs errors but doesn't crash")

async def bot_integration_example():
    """
    Example showing how to integrate with the Gromozeka bot
    """
    print("\n=== Bot Integration Example ===")
    
    # This would be in your bot handlers
    async def weather_command_handler(city_name: str) -> str:
        """
        Example bot command handler for weather
        """
        # Initialize from config
        config = ConfigManager()
        weather_config = config.getOpenWeatherMapConfig()
        
        if not weather_config.get('api-key') or weather_config.get('api-key') == 'YOUR_OPENWEATHERMAP_API_KEY':
            return "❌ OpenWeatherMap API key not configured, dood!"
        
        # Initialize client
        cache = DictWeatherCache()
        
        async with OpenWeatherMapClient(
            apiKey=weather_config['api-key'],
            cache=cache,
            geocodingTTL=weather_config.get('geocoding-cache-ttl', 2592000),
            weatherTTL=weather_config.get('weather-cache-ttl', 3600),
            requestTimeout=weather_config.get('request-timeout', 10),
            defaultLanguage=weather_config.get('default-language', 'ru')
        ) as client:
            
            # Get weather
            result = await client.getWeatherByCity(city_name)
            
            if result:
                location = result['location']
                weather = result['weather']
                current = weather['current']
                
                # Format message for Telegram
                message = f"""
🌍 **{location['name']}, {location['country']}**
{location['local_names'].get('ru', '')}

🌡️ **Температура:** {current['temp']}°C (ощущается как {current['feels_like']}°C)
☁️ **Облачность:** {current['clouds']}%
💨 **Ветер:** {current['wind_speed']} м/с
💧 **Влажность:** {current['humidity']}%
📊 **Давление:** {current['pressure']} гПа

{current['weather_description']}
"""
                return message.strip()
            else:
                return f"❌ Город '{city_name}' не найден, dood!"
    
    # Example usage
    message = await weather_command_handler("Moscow")
    print("Bot response:")
    print(message)

async def configuration_example():
    """
    Example showing different configuration options
    """
    print("\n=== Configuration Example ===")
    
    cache = DictWeatherCache()
    
    # Example 1: Fast cache for development
    print("Development config (fast cache expiry):")
    async with OpenWeatherMapClient(
        apiKey="your_api_key_here",
        cache=cache,
        geocodingTTL=300,    # 5 minutes
        weatherTTL=60,       # 1 minute
        requestTimeout=5,    # Fast timeout
        defaultLanguage="en"
    ) as client:
        print("✅ Client configured for development")
    
    # Example 2: Production config
    print("Production config (longer cache, Russian language):")
    async with OpenWeatherMapClient(
        apiKey="your_api_key_here",
        cache=cache,
        geocodingTTL=2592000,  # 30 days
        weatherTTL=3600,       # 1 hour
        requestTimeout=10,     # Longer timeout
        defaultLanguage="ru"   # Russian descriptions
    ) as client:
        print("✅ Client configured for production")

async def main():
    """
    Run all examples
    """
    print("🌤️  OpenWeatherMap Client Examples")
    print("=" * 50)
    
    # Note: These examples require a valid API key to work
    print("⚠️  Note: Replace 'your_api_key_here' with a real OpenWeatherMap API key")
    print("   Get one free at: https://openweathermap.org/api")
    print()
    
    try:
        await basic_usage_example()
        await step_by_step_example()
        await multiple_cities_example()
        await cache_demonstration()
        await error_handling_example()
        await bot_integration_example()
        await configuration_example()
        
        print("\n✅ All examples completed successfully, dood!")
        
    except Exception as e:
        print(f"\n❌ Example failed: {e}")
        print("This is expected if you don't have a valid API key")

if __name__ == "__main__":
    # Run examples
    asyncio.run(main())