import websocket
import json
import requests
import time
import sys
import os
from datetime import datetime
from collections import defaultdict
import hashlib

class GoldenFlowerRoundAnalyzer:
    def __init__(self):
        self.uid = 28465485
        self.channel = "poppo"
        self.mqtt_token = None
        self.ws = None
        
        # Round tracking
        self.current_round_id = None
        self.current_game_state = -1
        self.round_data = defaultdict(dict)
        self.completed_rounds = []
        self.round_number = 0
        
        # Auto-reconnect settings
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.reconnect_delay = 5  # seconds
        
        # File for saving results
        self.results_file = f"goldenflower_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        print(f"📁 Results will be saved to: {self.results_file}")
    
    def get_token(self):
        """Get MQTT token from API"""
        url = "https://game-hub.vshowapi.com/auth/getToken"
        
        params = {
            "source": "game-center",
            "backend_token": "",
            "dev": "",
            "_uid": str(self.uid),
            "smei_id": "BM4zBDhM+NKGp1K8slKsGRvWwAvqmld/Pue8DlmD2fwYrUi0B67IaJ9/2WQHsROVDFU6RaikzNdB7lDK1DOnKcw==",
            "uuid": "9db37d008cd0d345",
            "p": "android",
            "v": "522",
            "c": self.channel,
            "l": "en",
            "_sign": "JUvpoCsu2jlS1tH2FJxIvfDHT+9KNzd1w3Un1cqHVnbfDg==",
            "_random": "WJi9GQI3fY/aMqDaIHYN6al1VEsRIHL2"
        }
        
        try:
            print("🔑 Getting token...")
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data.get("code") == 200:
                    self.mqtt_token = data["data"]["mqtt_access_token"]
                    print("✅ Token obtained")
                    return True
        except Exception as e:
            print(f"❌ Failed to get token: {e}")
            
        return False
    
    def create_mqtt_connect(self):
        """Create MQTT CONNECT packet"""
        client_id = self.mqtt_token.encode('utf-8')
        
        packet = bytearray()
        packet.append(0x10)
        
        var_header = bytearray()
        var_header.extend(b'\x00\x04MQTT')
        var_header.append(4)
        var_header.append(0xC2)
        var_header.extend(b'\x13\x88')
        
        payload = bytearray()
        payload.extend(len(client_id).to_bytes(2, 'big'))
        payload.extend(client_id)
        payload.extend(b'\x00\x08username')
        payload.extend(b'\x00\x08password')
        
        remaining = len(var_header) + len(payload)
        enc_len = bytearray()
        while remaining > 0:
            enc_byte = remaining % 128
            remaining = remaining // 128
            if remaining > 0:
                enc_byte = enc_byte | 128
            enc_len.append(enc_byte)
        
        final_packet = bytearray([0x10])
        final_packet.extend(enc_len)
        final_packet.extend(var_header)
        final_packet.extend(payload)
        
        return bytes(final_packet)
    
    def create_mqtt_subscribe(self, packet_id, topic):
        """Create MQTT SUBSCRIBE packet"""
        topic_bytes = topic.encode('utf-8')
        
        payload = bytearray()
        payload.extend(packet_id.to_bytes(2, 'big'))
        payload.extend(len(topic_bytes).to_bytes(2, 'big'))
        payload.extend(topic_bytes)
        payload.append(0)
        
        remaining = len(payload)
        enc_len = bytearray()
        while remaining > 0:
            enc_byte = remaining % 128
            remaining = remaining // 128
            if remaining > 0:
                enc_byte = enc_byte | 128
            enc_len.append(enc_byte)
        
        final_packet = bytearray([0x82])
        final_packet.extend(enc_len)
        final_packet.extend(payload)
        
        return bytes(final_packet)
    
    def create_publish_packet(self, topic, message):
        """Create MQTT PUBLISH packet"""
        topic_bytes = topic.encode('utf-8')
        message_bytes = message.encode('utf-8')
        
        packet = bytearray([0x30])
        
        remaining = 2 + len(topic_bytes) + len(message_bytes)
        enc_len = bytearray()
        while remaining > 0:
            enc_byte = remaining % 128
            remaining = remaining // 128
            if remaining > 0:
                enc_byte = enc_byte | 128
            enc_len.append(enc_byte)
        
        final_packet = bytearray([0x30])
        final_packet.extend(enc_len)
        final_packet.extend(len(topic_bytes).to_bytes(2, 'big'))
        final_packet.extend(topic_bytes)
        final_packet.extend(message_bytes)
        
        return bytes(final_packet)
    
    def parse_mqtt_packet(self, data):
        """Parse MQTT packet"""
        if len(data) < 2:
            return None
        
        packet_type = (data[0] >> 4) & 0x0F
        
        if packet_type == 3:  # PUBLISH
            pos = 1
            while data[pos] & 0x80:
                pos += 1
            pos += 1
            
            topic_len = (data[pos] << 8) | data[pos + 1]
            pos += 2
            
            topic = data[pos:pos + topic_len].decode('utf-8', errors='ignore')
            pos += topic_len
            
            message = data[pos:].decode('utf-8', errors='ignore')
            
            return {"topic": topic, "message": message}
        
        return None
    
    def generate_round_id(self, json_data):
        """Generate a unique ID for this round based on bet amounts and cards"""
        sys_info = json_data.get("sys_info", {})
        
        # Create a hash from bet amounts and cards
        hash_input = ""
        
        bet_info = sys_info.get("bet_info", {})
        for option_id in ["0", "1", "2"]:
            info = bet_info.get(option_id, {})
            hash_input += f"{option_id}:{info.get('pay_amount', 0)}:{info.get('bean_pay_amount', 0)}|"
        
        # Add cards to hash
        for i in range(1, 10):
            key = f"result_pk_num{i}"
            hash_input += f"{sys_info.get(key, 0)}:"
        
        return hashlib.md5(hash_input.encode()).hexdigest()[:8]
    
    def analyze_bet_pattern(self, bet_info):
        """Analyze the betting pattern - who has highest, medium, lowest diamonds"""
        bets = {}
        for option_id in ["0", "1", "2"]:
            info = bet_info.get(option_id, {})
            real_diamonds = info.get("pay_amount", 0)
            beans = info.get("bean_pay_amount", 0)
            option_name = self.get_option_name(int(option_id))
            bets[option_name] = {
                "id": int(option_id),
                "diamonds": real_diamonds,
                "beans": beans,
                "total": real_diamonds + beans
            }
        
        # Sort by diamonds (real money)
        sorted_by_diamonds = sorted(bets.items(), key=lambda x: x[1]["diamonds"], reverse=True)
        sorted_by_total = sorted(bets.items(), key=lambda x: x[1]["total"], reverse=True)
        
        pattern = {
            "by_diamonds": {
                "highest": sorted_by_diamonds[0][0] if len(sorted_by_diamonds) > 0 else None,
                "medium": sorted_by_diamonds[1][0] if len(sorted_by_diamonds) > 1 else None,
                "lowest": sorted_by_diamonds[2][0] if len(sorted_by_diamonds) > 2 else None
            },
            "by_total": {
                "highest": sorted_by_total[0][0] if len(sorted_by_total) > 0 else None,
                "medium": sorted_by_total[1][0] if len(sorted_by_total) > 1 else None,
                "lowest": sorted_by_total[2][0] if len(sorted_by_total) > 2 else None
            },
            "diamonds_spread": sorted_by_diamonds[0][1]["diamonds"] - sorted_by_diamonds[-1][1]["diamonds"] if len(sorted_by_diamonds) >= 2 else 0,
            "total_spread": sorted_by_total[0][1]["total"] - sorted_by_total[-1][1]["total"] if len(sorted_by_total) >= 2 else 0
        }
        
        return pattern
    
    def analyze_packet(self, json_data):
        """Analyze and display packet data"""
        action = json_data.get("action", "")
        
        if action != "updateSysInfo":
            return
        
        sys_info = json_data.get("sys_info", {})
        game_state = sys_info.get("gameState", -1)
        winner_id = sys_info.get("bet_id", -1)
        
        # Generate round ID for tracking
        round_id = self.generate_round_id(json_data)
        
        # Check if this is a new round starting (game state changed from 0 to 1)
        if game_state == 1 and self.current_game_state == 0:
            # New round started
            self.current_round_id = round_id
            self.round_number += 1
            print(f"\n🎮 NEW ROUND #{self.round_number} STARTED")
            print("═" * 80)
        
        # Update game state
        self.current_game_state = game_state
        
        # Store data for this round
        self.round_data[round_id] = {
            "timestamp": datetime.now().isoformat(),
            "game_state": game_state,
            "winner_id": winner_id,
            "bet_info": sys_info.get("bet_info", {}),
            "award_amount": sys_info.get("award_amount", 0),
            "cards": self.extract_cards(sys_info),
            "points": self.extract_points(sys_info)
        }
        
        # Only show betting phase updates occasionally to avoid spam
        if game_state == 1 and winner_id == -1:
            # Show only every 5th update during betting to see progress
            bet_info = sys_info.get("bet_info", {})
            if len(self.round_data) % 5 == 0:
                total_real = sum(bet_info.get(str(i), {}).get("pay_amount", 0) for i in range(3))
                print(f"📊 Betting update: {total_real:,} total diamonds")
            return
        
        # If we have a winner and cards (final result), analyze and save
        if game_state == 0 and winner_id != -1 and self.has_cards(sys_info):
            # Check if we've already processed this round result
            if round_id in self.completed_rounds:
                return  # Skip duplicate
            
            self.completed_rounds.append(round_id)
            self.analyze_round_result(json_data, round_id)
    
    def extract_cards(self, sys_info):
        """Extract card values from sys_info"""
        cards = []
        for i in range(1, 10):
            key = f"result_pk_num{i}"
            cards.append(sys_info.get(key, 0))
        return cards
    
    def extract_points(self, sys_info):
        """Extract player points from sys_info"""
        points = []
        for i in range(3):
            key = f"result_point_{i}"
            points.append(sys_info.get(key, 0))
        return points
    
    def has_cards(self, sys_info):
        """Check if cards have been revealed (not all zeros)"""
        cards = self.extract_cards(sys_info)
        return any(cards)  # True if any card is non-zero
    
    def analyze_round_result(self, json_data, round_id):
        """Analyze and display final round result"""
        sys_info = json_data.get("sys_info", {})
        bet_info = sys_info.get("bet_info", {})
        winner_id = sys_info.get("bet_id", -1)
        award_amount = sys_info.get("award_amount", 0)
        
        print(f"\n🏁 FINAL RESULT - Round #{self.round_number}")
        print("═" * 80)
        
        # Display phase info
        print(f"⏱️  Time: {sys_info.get('time', 0)}s | Game State: {self.current_game_state}")
        
        # Analyze betting pattern
        print("\n📊 BETTING PATTERN ANALYSIS")
        print("─" * 80)
        
        pattern = self.analyze_bet_pattern(bet_info)
        
        # Display diamonds for each option with ranking
        total_real = 0
        winner_bet = 0
        
        for option_id in ["0", "1", "2"]:
            info = bet_info.get(option_id, {})
            real_diamonds = info.get("pay_amount", 0)
            beans = info.get("bean_pay_amount", 0)
            option_name = self.get_option_name(int(option_id))
            
            is_winner = (winner_id == int(option_id))
            winner_marker = "🏆" if is_winner else "  "
            
            # Determine ranking emoji
            ranking = ""
            if pattern["by_diamonds"]["highest"] == option_name:
                ranking = "🥇 "
            elif pattern["by_diamonds"]["medium"] == option_name:
                ranking = "🥈 "
            elif pattern["by_diamonds"]["lowest"] == option_name:
                ranking = "🥉 "
            
            print(f"{winner_marker} {ranking}Option {option_name}: {real_diamonds:,} 💎 | {beans:,} 🫘")
            
            total_real += real_diamonds
            if is_winner:
                winner_bet = real_diamonds
        
        print(f"\n💰 TOTAL REAL DIAMONDS BET: {total_real:,}")
        
        # Show betting pattern analysis
        print(f"\n📈 BET RANKING (by 💎 diamonds):")
        print(f"   Highest: Option {pattern['by_diamonds']['highest']} 🥇")
        print(f"   Medium:  Option {pattern['by_diamonds']['medium']} 🥈")
        print(f"   Lowest:  Option {pattern['by_diamonds']['lowest']} 🥉")
        print(f"   Spread: {pattern['diamonds_spread']:,} diamonds")
        
        # House edge analysis
        print("\n🏠 HOUSE EDGE ANALYSIS")
        print("─" * 80)
        
        print(f"✅ Winner: Option {self.get_option_name(winner_id)} (ID: {winner_id})")
        print(f"📊 Total Real Bet: {total_real:,}")
        print(f"🎁 Payout to Winner: {award_amount:,}")
        
        house_take = total_real - award_amount
        house_edge_pct = (house_take / total_real * 100) if total_real > 0 else 0
        
        print(f"🏠 House Takes: {house_take:,}")
        print(f"📈 House Edge: {house_edge_pct:.2f}%")
        
        # Odds analysis (2.98x)
        expected_payout = winner_bet * 2.98
        print(f"\n🎰 ODDS ANALYSIS (2.98x)")
        print(f"   Winner bet: {winner_bet:,}")
        print(f"   Expected payout: {expected_payout:,.0f}")
        print(f"   Actual payout: {award_amount:,}")
        
        if expected_payout > 0:
            diff_pct = ((expected_payout - award_amount) / expected_payout) * 100
            if diff_pct > 0:
                print(f"   💰 House keeps: {diff_pct:.2f}% more than expected")
            else:
                print(f"   🎉 Players get: {abs(diff_pct):.2f}% more than expected")
        
        # Check if winner was highest bettor
        winner_name = self.get_option_name(winner_id)
        if pattern["by_diamonds"]["highest"] == winner_name:
            print(f"\n⚠️  PATTERN: Winner had the MOST diamonds (🥇)")
        elif pattern["by_diamonds"]["lowest"] == winner_name:
            print(f"\n⚠️  PATTERN: Winner had the LEAST diamonds (🥉)")
        elif pattern["by_diamonds"]["medium"] == winner_name:
            print(f"\n⚠️  PATTERN: Winner had MEDIUM diamonds (🥈)")
        
        # Card display
        print("\n🃏 CARDS REVEALED")
        print("─" * 80)
        
        cards = self.extract_cards(sys_info)
        points = self.extract_points(sys_info)
        
        print(f"   Cards: {cards}")
        print(f"\n   Player A cards: {cards[0:3]} | Points: {points[0]}")
        print(f"   Player B cards: {cards[3:6]} | Points: {points[1]}")
        print(f"   Player C cards: {cards[6:9]} | Points: {points[2]}")
        
        # Save this round result to JSON file
        self.save_round_result(json_data, pattern, house_edge_pct, house_take)
        
        # Show statistics after each completed round
        self.show_statistics()
    
    def save_round_result(self, json_data, pattern, house_edge_pct, house_take):
        """Save round result to JSON file"""
        sys_info = json_data.get("sys_info", {})
        
        round_result = {
            "round_number": self.round_number,
            "timestamp": datetime.now().isoformat(),
            "winner": {
                "id": sys_info.get("bet_id", -1),
                "name": self.get_option_name(sys_info.get("bet_id", -1))
            },
            "betting_pattern": pattern,
            "house_edge": {
                "percentage": house_edge_pct,
                "amount": house_take
            },
            "bets": {
                "A": sys_info.get("bet_info", {}).get("0", {}).get("pay_amount", 0),
                "B": sys_info.get("bet_info", {}).get("1", {}).get("pay_amount", 0),
                "C": sys_info.get("bet_info", {}).get("2", {}).get("pay_amount", 0)
            },
            "cards": self.extract_cards(sys_info),
            "points": self.extract_points(sys_info),
            "total_bet": sum(sys_info.get("bet_info", {}).get(str(i), {}).get("pay_amount", 0) for i in range(3)),
            "payout": sys_info.get("award_amount", 0)
        }
        
        # Read existing results
        existing_results = []
        if os.path.exists(self.results_file):
            try:
                with open(self.results_file, 'r') as f:
                    existing_results = json.load(f)
            except:
                existing_results = []
        
        # Append new result
        existing_results.append(round_result)
        
        # Write back to file
        with open(self.results_file, 'w') as f:
            json.dump(existing_results, f, indent=2)
        
        print(f"💾 Result saved to {self.results_file}")
    
    def show_statistics(self):
        """Show statistics of completed rounds"""
        if not self.completed_rounds:
            return
        
        total_rounds = len(self.completed_rounds)
        
        # Read results from file to get accurate stats
        if not os.path.exists(self.results_file):
            return
        
        try:
            with open(self.results_file, 'r') as f:
                all_results = json.load(f)
        except:
            return
        
        if not all_results:
            return
        
        print(f"\n📈 ROUND STATISTICS ({total_rounds} rounds completed)")
        print("═" * 80)
        
        # Winner distribution
        winner_counts = {}
        pattern_counts = {
            "winner_highest": 0,
            "winner_medium": 0,
            "winner_lowest": 0
        }
        
        total_house_take = 0
        total_bet = 0
        
        for result in all_results:
            winner = result["winner"]["name"]
            winner_counts[winner] = winner_counts.get(winner, 0) + 1
            
            # Check betting pattern for winner
            pattern = result["betting_pattern"]
            winner_name = result["winner"]["name"]
            
            if pattern["by_diamonds"]["highest"] == winner_name:
                pattern_counts["winner_highest"] += 1
            elif pattern["by_diamonds"]["medium"] == winner_name:
                pattern_counts["winner_medium"] += 1
            elif pattern["by_diamonds"]["lowest"] == winner_name:
                pattern_counts["winner_lowest"] += 1
            
            total_house_take += result["house_edge"]["amount"]
            total_bet += result["total_bet"]
        
        print(f"Winner distribution:")
        for winner, count in sorted(winner_counts.items()):
            pct = (count / total_rounds) * 100
            print(f"  {winner}: {count} times ({pct:.1f}%)")
        
        print(f"\nBetting patterns when winner wins:")
        print(f"  Winner had MOST diamonds: {pattern_counts['winner_highest']} times ({pattern_counts['winner_highest']/total_rounds*100:.1f}%)")
        print(f"  Winner had MEDIUM diamonds: {pattern_counts['winner_medium']} times ({pattern_counts['winner_medium']/total_rounds*100:.1f}%)")
        print(f"  Winner had LEAST diamonds: {pattern_counts['winner_lowest']} times ({pattern_counts['winner_lowest']/total_rounds*100:.1f}%)")
        
        if total_bet > 0:
            overall_edge = (total_house_take / total_bet) * 100
            print(f"\nOverall house edge: {overall_edge:.2f}%")
            print(f"Total house profit: {total_house_take:,} diamonds")
            print(f"Total diamonds bet: {total_bet:,}")
    
    def get_option_name(self, option_id):
        """Convert option ID to letter"""
        if option_id == 0:
            return "A"
        elif option_id == 1:
            return "B"
        elif option_id == 2:
            return "C"
        else:
            return "Unknown"
    
    def connect_websocket(self):
        """Connect to WebSocket with auto-retry"""
        attempts = 0
        max_attempts = 3
        
        while attempts < max_attempts:
            try:
                if not self.mqtt_token and not self.get_token():
                    print("❌ Failed to get token, retrying...")
                    attempts += 1
                    time.sleep(2)
                    continue
                
                ws_url = "wss://game-wss.vshowapi.com/mqtt"
                
                headers = {
                    "Origin": "https://fun.vshow-play.com",
                    "Sec-WebSocket-Protocol": "mqtt",
                    "User-Agent": "Mozilla/5.0",
                    "Accept-Encoding": "gzip, deflate, br, zstd",
                    "Accept-Language": "en-US,en;q=0.9"
                }
                
                print("🔌 Connecting to WebSocket...")
                self.ws = websocket.WebSocket()
                self.ws.connect(ws_url, header=headers)
                print("✅ WebSocket connected")
                
                connect_packet = self.create_mqtt_connect()
                self.ws.send_binary(connect_packet)
                
                response = self.ws.recv()
                if response[0] == 0x20 and response[1] == 0x02 and response[3] == 0x00:
                    print("✅ MQTT connection successful")
                    
                    topics = [
                        (1, "goldenflower/broadcast"),
                        (2, f"goldenflower/{self.uid}"),
                        (3, f"global/{self.uid}")
                    ]
                    
                    for packet_id, topic in topics:
                        subscribe_packet = self.create_mqtt_subscribe(packet_id, topic)
                        self.ws.send_binary(subscribe_packet)
                        self.ws.recv()
                    
                    join_msg = json.dumps({"lang": "en"})
                    publish_packet = self.create_publish_packet("goldenflower/user_join", join_msg)
                    self.ws.send_binary(publish_packet)
                    
                    self.reconnect_attempts = 0  # Reset reconnect counter on successful connection
                    return True
                else:
                    print("❌ MQTT connection failed, retrying...")
                    attempts += 1
                    time.sleep(2)
                    
            except Exception as e:
                print(f"❌ Connection failed: {e}")
                attempts += 1
                if attempts < max_attempts:
                    print(f"🔄 Retrying in 2 seconds... (Attempt {attempts}/{max_attempts})")
                    time.sleep(2)
        
        print("❌ Failed to connect after multiple attempts")
        return False
    
    def auto_reconnect(self):
        """Handle automatic reconnection"""
        self.reconnect_attempts += 1
        
        if self.reconnect_attempts > self.max_reconnect_attempts:
            print(f"❌ Max reconnection attempts ({self.max_reconnect_attempts}) reached. Giving up.")
            return False
        
        print(f"\n🔄 Connection lost! Attempting to reconnect... (Attempt {self.reconnect_attempts}/{self.max_reconnect_attempts})")
        
        # Close existing connection if it exists
        if self.ws:
            try:
                self.ws.close()
            except:
                pass
        
        # Wait before retrying (with increasing delay)
        wait_time = self.reconnect_delay * self.reconnect_attempts
        print(f"⏳ Waiting {wait_time} seconds before reconnecting...")
        time.sleep(wait_time)
        
        # Try to reconnect
        if self.connect_websocket():
            print("✅ Reconnection successful!")
            return True
        else:
            return False
    
    def run(self):
        """Main execution with auto-reconnect"""
        print("=" * 80)
        print("🎯 GOLDEN FLOWER ROUND ANALYZER")
        print("=" * 80)
        print("Features:")
        print("• Tracks complete rounds (not individual updates)")
        print("• Compares diamond amounts (highest/medium/lowest)")
        print("• Saves only FINAL results to JSON file")
        print("• Analyzes betting patterns")
        print("• AUTO-RECONNECT on disconnection")
        print("=" * 80)
        
        if not self.get_token():
            return
        
        if not self.connect_websocket():
            return
        
        print(f"\n✅ Listening for packets...")
        print("📊 Will show betting updates occasionally")
        print("🏁 Will analyze COMPLETE rounds only")
        print("💾 Saving results to JSON file")
        print("🔄 Auto-reconnect enabled (max {self.max_reconnect_attempts} attempts)")
        print("⏸️  Press Ctrl+C to stop")
        print("=" * 80)
        
        last_packet_time = time.time()
        connection_check_interval = 30  # Check connection every 30 seconds
        
        try:
            while True:
                try:
                    self.ws.settimeout(1.0)
                    data = self.ws.recv()
                    
                    if data:
                        last_packet_time = time.time()
                        parsed = self.parse_mqtt_packet(data)
                        if parsed and parsed["topic"] == "goldenflower/broadcast":
                            try:
                                json_data = json.loads(parsed["message"])
                                if json_data.get("action") == "updateSysInfo":
                                    self.analyze_packet(json_data)
                            except json.JSONDecodeError:
                                pass
                        
                        if len(data) >= 1 and (data[0] >> 4) == 12:
                            pingresp = b'\xD0\x00'
                            self.ws.send_binary(pingresp)
                
                except websocket.WebSocketTimeoutException:
                    # Check if we haven't received packets for a while
                    current_time = time.time()
                    if current_time - last_packet_time > connection_check_interval:
                        # Send a ping to check connection
                        try:
                            ping_packet = b'\xC0\x00'  # PINGREQ packet
                            self.ws.send_binary(ping_packet)
                            # Wait for PINGRESP
                            self.ws.settimeout(5.0)
                            response = self.ws.recv()
                            if len(response) >= 1 and (response[0] >> 4) == 13:
                                last_packet_time = current_time
                        except:
                            # Connection seems dead, try to reconnect
                            if not self.auto_reconnect():
                                print("❌ Failed to reconnect, stopping...")
                                break
                    continue
                    
                except websocket.WebSocketConnectionClosedException:
                    print("\n🔌 WebSocket connection closed unexpectedly")
                    if not self.auto_reconnect():
                        print("❌ Failed to reconnect, stopping...")
                        break
                    
                except Exception as e:
                    print(f"\n❌ Error: {e}")
                    if not self.auto_reconnect():
                        print("❌ Failed to reconnect, stopping...")
                        break
        
        except KeyboardInterrupt:
            print("\n\n⏹️  Stopped by user")
        
        finally:
            # Final summary
            if self.completed_rounds:
                print(f"\n" + "=" * 80)
                print("📊 FINAL SUMMARY")
                print("=" * 80)
                print(f"Total rounds analyzed: {len(self.completed_rounds)}")
                print(f"Results saved to: {self.results_file}")
            
            if self.ws:
                try:
                    self.ws.close()
                    print("🔌 Connection closed")
                except:
                    pass

def main():
    """Main function"""
    analyzer = GoldenFlowerRoundAnalyzer()
    analyzer.run()

if __name__ == "__main__":
    main()
