from .hotel_booking_agent import agent as hotel_booking_agent
from .orchestrator_agent import agent as orchestrator_agent

if __name__ == "__main__":
    # start Registry
    hotel_booking_agent.start()

    input_query = input("Where would you like to travel? ")

    result = orchestrator_agent.get_user_input(input_query)
    print(result)
