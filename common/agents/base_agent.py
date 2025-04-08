import logging
import time

from client.network import NetworkManager
from common import move

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("game_debug.log"), logging.StreamHandler()],
)


class BaseAgent:
    """Base class for all agents, enforcing the implementation of get_move()."""

    def __init__(
        self,
        nickname: str,
        network: NetworkManager,
        logger: str = "client.agent"
    ):
        """
        Initialize the base agent. Not supposed to be modified.

        Args:
            nickname (str): The name of the agent
            network (NetworkManager): The network object to handle communication
            logger (str): The logger name

        Attributes:
            cell_size (int): The size of a cell in pixels
            game_width (int): The width of the game in cells
            game_height (int): The height of the game in cells
            all_trains (dict): Dictionary of all trains in the game
            passengers (list): List of passengers in the game
            delivery_zone (list): List of delivery zones in the game
        """
        self.logger = logging.getLogger(logger)
        self.nickname = nickname
        self.network = network

        # Game parameters, regularly updated by the client in handle_state_data() (see game_state.py)
        self.cell_size = None
        self.game_width = None
        self.game_height = None
        self.all_trains = None
        self.passengers = None
        self.delivery_zone = None

    def get_move(self):
        """
        Abstract method to be implemented by subclasses.
        Must return a valid move.Move.
        """
        pass

    def update_agent(self):
        """
        Regularly called by the client to send the new direction to the server. Not supposed to be modified.

        Returning from this method without doing anything will cause the train to continue moving forward.
        """
        new_direction = self.get_move()
        if new_direction not in move.Move:
            logging.error("get_move() did not return a valid move!")
            return

        if new_direction == move.Move.DROP:
            self.network.send_drop_wagon_request()
            return

        if new_direction != self.all_trains[self.nickname]["direction"]:
            self.network.send_direction_change(new_direction.value)
