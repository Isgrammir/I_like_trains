import pygame
import logging
import time
import threading
import sys
import importlib

from client.network import NetworkManager
from client.renderer import Renderer
from client.event_handler import EventHandler
from client.game_state import GameState

from common.config import Config
from common.client_config import GameMode


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("client")


class Client:
    """Main client class"""

    def __init__(self, config: Config):
        """Initialize the client"""
        self.config = config.client
        self.game_mode = self.config.game_mode

        # If we launch an observer, we want the host to be local_host, otherwise
        if self.game_mode == GameMode.OBSERVER:
            host = "localhost"
        else:
            host = self.config.host

        # Initialize state variables
        self.running = True
        self.is_dead = False
        self.waiting_for_respawn = False
        self.death_time = 0
        self.respawn_cooldown = 0
        self.is_initialized = False
        self.in_waiting_room = True
        self.lock = threading.Lock()

        # Game over variables
        self.game_over = False
        self.game_over_data = None
        self.final_scores = []

        # Name verification variables
        self.name_check_received = False
        self.name_check_result = False

        # Sciper verification variables
        self.sciper_check_received = False
        self.sciper_check_result = False

        # Game data
        self.trains = {}
        self.passengers = []
        self.delivery_zone = {}

        # TODO(alok): delete self.cell_size, use self.config.cell_size everywhere
        self.cell_size = 0
        self.game_width = 200  # Initial game area width
        self.game_height = 200  # Initial game area height

        # Space between game area and leaderboard
        self.game_screen_padding = 20
        self.leaderboard_width = self.config.leaderboard_width
        self.leaderboard_height = 2 * self.game_screen_padding + self.game_height

        self.leaderboard_data = []
        self.waiting_room_data = None

        # Calculate screen dimensions based on game area and leaderboard
        # TODO(alok): delete these and use self.config.screen_width and self.config.screen_height instead
        self.screen_width = self.config.screen_width
        self.screen_height = self.config.screen_height

        # Window creation flags and parameters
        self.window_needs_update = False
        self.window_update_params = {
            "width": self.screen_width,
            "height": self.screen_height,
        }

        # Initialize pygame but don't create window yet
        pygame.init()
        self.screen = pygame.display.set_mode(
            (self.screen_width, self.screen_height), pygame.RESIZABLE
        )
        pygame.display.set_caption("I Like Trains")
        self.is_initialized = True

        # Initialize components
        self.network = NetworkManager(self, host, self.config.port)
        self.renderer = Renderer(self)

        self.event_handler = EventHandler(self, self.game_mode)
        self.game_state = GameState(self, self.game_mode)

        # Initialize agent based on game mode
        self.agent = None

        logger.debug("Initialized client")

        if self.game_mode != GameMode.OBSERVER:
            logger.debug("Initializing agent")
            agent_info = self.config.agent
            if agent_info and hasattr(agent_info, "agent_file_name"):
                logger.info(f"Loading agent: {agent_info.agent_file_name}")
                agent_file_name = agent_info.agent_file_name
                if agent_file_name.endswith(".py"):
                    # Remove .py extension
                    agent_file_name = agent_file_name[:-3]

                # Construct the module path correctly
                module_path = f"common.agents.{agent_file_name}"
                logger.info(f"Importing module: {module_path}")

                # Add parent directory to Python path to allow importing agents package
                module = importlib.import_module(module_path)
                self.nickname = agent_info.nickname
                # self.agent_sciper = agent_info["sciper"]
                self.agent = module.Agent(self.nickname, self.network)

        self.ping_response_received = False
        self.server_disconnected = False

    def update_game_window_size(self, width, height):
        """Schedule window size update to be done in main thread"""
        with self.lock:
            self.window_needs_update = True
            self.window_update_params = {"width": width, "height": height}

    def handle_window_updates(self):
        """Process any pending window updates in the main thread"""
        with self.lock:
            if self.window_needs_update:
                width = self.window_update_params["width"]
                height = self.window_update_params["height"]

                try:
                    self.screen = pygame.display.set_mode(
                        (width, height), pygame.RESIZABLE
                    )
                    pygame.display.set_caption("I Like Trains")
                except Exception as e:
                    logger.error(f"Error updating window: {e}")

                self.window_needs_update = False

    def run(self):
        """Main client loop"""
        logger.info("Starting client loop")
        # Connect to server with timeout
        connection_timeout = 5  # 5 seconds timeout
        connection_start_time = time.time()

        connection_successful = False
        while time.time() - connection_start_time < connection_timeout:
            try:
                if self.network.connect():
                    # Verify connection by attempting to receive data
                    if self.network.verify_connection():
                        logger.info("Connected to server successfully")
                        connection_successful = True
                        break
                    else:
                        logger.warning(
                            "Connection reported success but failed verification"
                        )
                time.sleep(0.5)  # Small delay between connection attempts
            except Exception as e:
                logger.error(f"Connection attempt failed: {e}")
                time.sleep(0.5)

        if not connection_successful:
            logger.error(
                f"Failed to connect to server after {connection_timeout} seconds timeout"
            )
            # Show error message to user
            if self.screen:
                font = pygame.font.Font(None, 26)
                text = font.render(
                    "Connection to server failed. Check port and server status.",
                    True,
                    (255, 0, 0),
                )
                self.screen.fill((0, 0, 0))
                self.screen.blit(
                    text,
                    (
                        self.config.screen_width // 2 - text.get_width() // 2,
                        self.config.screen_height // 2 - text.get_height() // 2,
                    ),
                )
                pygame.display.flip()
                pygame.time.wait(3000)  # Show error for 3 seconds
            pygame.quit()
            return

        # Create a temporary window for player name
        temp_width, temp_height = self.config.screen_width, self.config.screen_height
        try:
            self.screen = pygame.display.set_mode((temp_width, temp_height))
            pygame.display.set_caption("I Like Trains - Login")
        except Exception as e:
            logger.error(f"Error creating login window: {e}")
            return

        if self.game_mode == GameMode.AGENT:
            nickname = self.config.agent.nickname
            sciper = self.config.sciper
        elif self.game_mode == GameMode.MANUAL:
            nickname = self.config.manual.nickname
            sciper = self.config.sciper
        else:
            nickname = ""
            sciper = ""
        
        logger.debug(f"Sending agent ids: {nickname}, {sciper}, {self.game_mode.value}")

        if not self.network.send_agent_ids(
            nickname,
            sciper,
            self.game_mode.value
        ):
            logger.error("Failed to send agent ids to server")
            return

        # Main loop
        clock = pygame.time.Clock()
        logger.info(f"Running client loop: {self.running}")
        while self.running:
            # Handle events
            self.event_handler.handle_events()
            # Handle any pending window updates in the main thread
            self.handle_window_updates()

            # Add automatic respawn logic
            if (
                not self.config.manual_spawn
                and self.is_dead
                and self.waiting_for_respawn
                and not self.game_over
            ):
                elapsed = time.time() - self.death_time
                if elapsed >= self.respawn_cooldown:
                    logger.debug("Sending spawn request.")
                    self.network.send_spawn_request()
   
            self.renderer.draw_game()

            # Limit FPS
            clock.tick(60)

        # Close connection
        self.network.disconnect()
        pygame.quit()

    def handle_state_data(self, data):
        """Handle state data received from server"""
        self.game_state.handle_state_data(data)

    def handle_death(self, data):
        """Handle cooldown data received from server"""
        self.game_state.handle_death(data)

    def handle_game_status(self, data):
        """Handle game status received from server"""
        self.game_state.handle_game_status(data)

    def handle_leaderboard_data(self, data):
        """Handle leaderboard data received from server"""
        self.game_state.handle_leaderboard_data(data)

    def handle_waiting_room_data(self, data):
        """Handle waiting room data received from server"""
        self.game_state.handle_waiting_room_data(data)

    def handle_drop_wagon_success(self, data):
        """Handle successful wagon drop response from server"""
        self.game_state.handle_drop_wagon_success(data)

    def handle_game_over(self, data):
        """Handle game over data received from server"""
        self.game_state.handle_game_over(data)

    def handle_initial_state(self, data):
        """Handle initial state message from server"""
        logger.info("Received initial state from server")

        # Store game lifetime and start time
        self.game_life_time = data.get(
            "game_life_time", 60
        )  # Default to 60 seconds if not provided
        self.game_start_time = time.time()  # Use client's time for consistency

        logger.info(f"Game lifetime set to {self.game_life_time} seconds")

    def get_remaining_time(self):
        """Calculate remaining game time in seconds"""
        if not hasattr(self, "game_life_time") or not hasattr(self, "game_start_time"):
            return None

        elapsed = time.time() - self.game_start_time
        remaining = max(0, self.game_life_time - elapsed)

        return remaining

    def handle_server_disconnection(self):
        """Handle server disconnection gracefully"""
        logger.warning("Server disconnected, shutting down client...")
        self.server_disconnected = True
        self.running = False

        # Afficher un message à l'utilisateur si pygame est initialisé
        if hasattr(self, "renderer") and self.renderer and pygame.display.get_init():
            try:
                font = pygame.font.SysFont("Arial", 24)
                text = font.render(
                    "Server disconnected. Press any key to exit.", True, (255, 0, 0)
                )
                text_rect = text.get_rect(
                    center=(
                        self.config.screen_width // 2,
                        self.config.screen_height // 2,
                    )
                )
                self.renderer.screen.fill((0, 0, 0))
                self.renderer.screen.blit(text, text_rect)
                pygame.display.flip()

                # Attendre que l'utilisateur appuie sur une touche
                waiting = True
                while waiting:
                    for event in pygame.event.get():
                        if event.type == pygame.QUIT or event.type == pygame.KEYDOWN:
                            waiting = False
                    time.sleep(0.1)
            except Exception as e:
                logger.error(f"Error displaying disconnection message: {e}")

        # Fermer proprement
        self.cleanup()

    def cleanup(self):
        """Clean up resources before exiting"""
        logger.info("Cleaning up resources...")

        # Fermer la connexion réseau
        if hasattr(self, "network") and self.network:
            self.network.disconnect()

        # Quitter pygame
        if pygame.display.get_init():
            pygame.quit()

        # Quitter le programme
        if self.server_disconnected:
            logger.info("Exiting due to server disconnection")
            sys.exit(0)
