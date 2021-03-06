# Pyhton Libraries
import argparse
import networkx
import random
import pandas as pd
import matplotlib.pyplot as plt
import time
import math
import os

# User defined libraries
from Attacker import Attacker
from Defender import Defender
from Message import Message

class GameEngine():
    """
        Class responsible for running the attacker/defender simulation of an IOT network.

        A network structure is provided via a text file to act as the battleground. The attacker
        is tasked with trying to mask it's activity on the network in order to successfully execute
        phishing attacks. While the defender is trying to detect this malicious behavior and reject
        those infected communications. Each side is given a number of lives, upon being breached the
        defender loses one life. Upon being detected the attacker loses one life. The game is played
        until one of the two run out of lives. The thought process of the attacker in terms of how
        suspicous a node is in the network is updated during play. Random background traffic of the
        network is also simulated for the attacker to slip inbetween to avoid detection.

        Reinforcement learning is utilized at the end of every game using Q learning to improve both
        combatants in their roles.
    """

    ### Static Class Variables
    MAX_BACKGROUND_TRAFFIC_MESSAGES = 30                      # The maximum number of background messages between attacks

    COLOR_MAP = {Defender.NO_SUSPICION_LABEL  : 'blue', Defender.LOW_SUSPICION_LABEL  : 'yellow', Defender.MEDIUM_SUSPICION_LABEL :  'orange', Defender.HIGH_SUSPICION_LABEL : 'red'}
    NOT_INFECTED_MARKER = 'o'                                 # Non-infected nodes show up as circles
    INFECTED_MARKER = 'X'                                     # Infected nodes appear as filled X markers
    GRAPH_DELAY = 2                                           # Time delay in seconds between graph updates
    NODE_SIZE = 100                                           # Size of nodes when being graphed

    # Indicies for the network file
    NETWORK_SOURCE_IP_INDEX = 0
    NETWORK_SINK_IP_INDEX = 1

    GAME_LOG_PATH    =      '../local_logs/GAME_LOG.csv'      # Default path to the dir where game logs are saved for user review            
    GAME_LOG_HEADERS =      'Network,Rounds Played,Defender Degree,Attacker Degree, Defender Clustering, Attacker Clustering,Num Defenders, Num Attackers'
    GAME_ROW_STRING  =      '{0},{1},{2},{3},{4},{5},{6},{7}\n'

    ###  Method functions
    
    def __init__(self, trafficPath, attackPath, networkPath, loadModels= False, epsilon= 1, visualize= True):
        """Class constructor
        Parameters
        ----------
        trafficPath
            String representing the file path to the dataset used for background messages

        attackPath
            String representing the file path to the dataset used for attack messages

        networkPath
            String representing the file path to the network parameters file

        loadModels
            Boolean describing whether previous models are loaded in for this game or new ones are initialized
            
        epsilon
            float from 0 to 1 representing the probability that each player makes random moves 

        visualize
            boolean representing whether or not the game should be visualized

        Returns
        -------
        None
        """
        self.firstGame = True
        self.visualizeGame = visualize
        self.trafficPath = trafficPath
        self.attackPath = attackPath
        self.networkPath = networkPath
        self.loadModels = loadModels
        self.startingEpsilon = epsilon
        self.initializeGame()

    def initializeGame(self):
        """Initializes the starting game state, both players, and loads in the dataset
           Should be called after each game is played to prepare for the next one
        Parameters
        ----------
        None
        
        Returns
        -------
        None
        """
        self.colorMap = {}
        self.loadTrafficDataset(self.trafficPath)
        self.initializeNetwork(self.networkPath)
        self.roundNumber = 0

        if self.firstGame:
            self.firstGame = False
            self.attacker = Attacker(datasetPath= self.attackPath, networkSize= len(self.graph.nodes()), epsilon= self.startingEpsilon)
            self.defender = Defender(epsilon= self.startingEpsilon)
            if self.loadModels:
                self.attacker.loadModel()
                self.attacker.epsilon = Attacker.EPSILON_MIN
                self.defender.loadModel()
                self.defender.epsilon = Defender.EPSILON_MIN
        else:
            self.attacker.prepareForNextGame()
            self.defender.prepareForNextGame()
            
        
    def loadTrafficDataset(self, trafficPath):
        """loads in the dataset for generating background traffic
        Parameters
        ----------
        trafficPath
            String representing the file path to the dataset used for background traffic
        
        Returns
        -------
        None
        """
        self.dataset = pd.read_csv(trafficPath)

    def initializeNetwork(self, networkPath):
        """loads in the network parameters and creates a networkx graph
        Parameters
        ----------
        networkPath
            String representing the file path to the network parameters file
        
        Returns
        -------
        None
        """
        plt.ion()
        self.graph = networkx.DiGraph()
        with open(networkPath, 'r') as file:
            lines = file.readlines()[1:]
            for line in lines:
                elems = line.split(',')
                sourceIP = elems[GameEngine.NETWORK_SOURCE_IP_INDEX].strip()
                sinkIP = elems[GameEngine.NETWORK_SINK_IP_INDEX].strip()

                if not self.graph.has_node(sourceIP):
                    self.graph.add_node(sourceIP)
                    self.colorMap[sourceIP] = GameEngine.COLOR_MAP[Defender.NO_SUSPICION_LABEL]
                if not self.graph.has_node(sinkIP):
                    self.graph.add_node(sinkIP)
                    self.colorMap[sinkIP] = GameEngine.COLOR_MAP[Defender.NO_SUSPICION_LABEL]
                self.graph.add_edge(sourceIP, sinkIP)

        allNodes = [node for node in self.graph.nodes()]
        self.infectedNodes = random.sample(allNodes, 1)
        self.reachableNodes = [int(self.isReachable(node)) for node in allNodes]
        self.quarantinedNodes = []

    def runGame(self):
        """Runs through one instance of the game,
           game ends when one player runs out of lives
        Parameters
        ----------
        None
        
        Returns
        -------
        None
        """
        self.wait = False
        while not self.gameOver():
           self.roundNumber += 1
           organizedQueues, trafficInfo, attackIndex = self.generateTrafficQueues()
           self.lastAttackerScore = 0
           if self.visualizeGame: self.displayGraph(displayAttack= True)
           for queue in organizedQueues.values():
               for message in queue:
                   if not self.graph.has_edge(message.origin, message.destination): continue
                   skipped = False
                   if random.random() > self.calculateInspectionChance(len(queue)): 
                       if self.visualizeGame: print('Current message', str(message), ' was skipped inspection')
                       suspicionLabel = Defender.NO_SUSPICION_LABEL
                       skipped = True
                   else:
                       suspicionLabel = self.defender.inspect(message)

                   attackerReward, defenderReward = self.calculateScore(message, suspicionLabel)
                   self.updateNetwork(message, suspicionLabel)

                   if not skipped: self.defender.addTrainingPoint(message, suspicionLabel, defenderReward)
                   if message.isMalicious(): 
                       self.attacker.addTrainingPoint(trafficInfo, attackIndex, attackerReward)
                       self.lastAttackerScore = attackerReward

                   if self.visualizeGame: print('Current message', str(message), 'was given a suspicion label of:', suspicionLabel)
           if self.visualizeGame: self.displayGraph()

    def gameOver(self):
        """Returns true if one player is out of lives"""
        return not any(self.reachableNodes)

    def generateTrafficQueues(self):
        """Fills the game queue with a random number of background messages,
           then randomly inserts the attack message into the queue
        Parameters
        ----------
        None
        
        Returns
        -------
        organizedQueues
            Dictionary with keys of node IPs and values representing the queue of message for that node

        trafficInfo
            Array containing information regarding each node about reachability, reward, and current traffic load
        
        attackIndex
            Integer representing the index in the set of graph nodes that is being attacked
        """
        self.traffic = self.generateBackgroundTraffic()
        organizedQueues = {node : [message for message in self.traffic if message.destination == node] for node in self.graph.nodes()}
        
        nodeInformation = [[len(organizedQueues[node]), self.isReachable(node), self.calculateNodeInfectionReward(node)] for node in self.graph.nodes()]
        trafficFlow, reachable, infectionScores = list(zip(*nodeInformation))
        trafficInfo = (trafficFlow + reachable + infectionScores)
        
        self.attackMessage, attackIndex = self.attacker.getAttack(trafficFlow, reachable, infectionScores, self.infectedNodes, self.graph)
        if self.attackMessage != None:
            position = random.randint(0, len(organizedQueues[self.attackMessage.destination]) + 1)
            organizedQueues[self.attackMessage.destination].insert(position, self.attackMessage)
        else:
            self.attacker.addTrainingPoint(trafficInfo, self.attacker.OUTPUT_SIZE - 1, 0)
            
        return organizedQueues, trafficInfo, attackIndex

    def generateBackgroundTraffic(self):
        """Generate a random number of background messages from the dataset
        Parameters
        ----------
        None
        
        Returns
        -------
        None
        """
        messages = []
        numMessages = random.randint(1, GameEngine.MAX_BACKGROUND_TRAFFIC_MESSAGES)
        datasetLength = len(self.dataset.index)
        rowIndices = [random.randint(1, datasetLength - 1) for _ in range(numMessages)]
        rows = [list(self.dataset.iloc[index]) for index in rowIndices]
        for row in rows:            
            nodes = [node for node in self.graph.nodes()]
            newOrigin = random.choice(nodes)
            row[Message.ORIGIN_INDEX] = newOrigin
            try:
                row[Message.DESTINATION_INDEX] = random.choice([node for node in nodes if self.graph.has_edge(newOrigin, node)])    # Pick destination as random node that it has a connection with
            except: 
                continue
            messages.append(Message(row))
        return messages

    def calculateInspectionChance(self, queueLength):
        """Returns the probability of checking a message based on the size of the queue it's in
        """
        return 2.195 - (1 / (1 + math.exp(-.75 * queueLength))) - (1 / (1 + math.exp(-.05 *queueLength)))

    def updateNetwork(self, message, label):
        """Recolor the graph based on the new label

        Parameters
        ----------
        message
            message object that contains metadata about the message being inspected

       label
           String label representing the suspicion category the message falls into
        
        Returns
        -------
        None
        """
        self.colorMap[message.origin] = GameEngine.COLOR_MAP[label]
        if label == Defender.HIGH_SUSPICION_LABEL or label == Defender.MEDIUM_SUSPICION_LABEL:
            self.quarantineNode(message.origin, message.destination, label)
        elif message.isMalicious():
            self.infectNode(message.destination)

        self.reachableNodes = [int(self.isReachable(node)) for node in self.graph.nodes()]

    def quarantineNode(self, origin, destination, label):
        """Remove outgoing edges from a node effectively hindering it from spreading infection
        Parameters
        ----------
        origin
            IP of the sender of the suspected infected message

        destination
            IP of the intended receipent of the suspected infected message

       label
           String label representing the suspicion category the message falls into
           Determines the strength of the quarantine
        
        Returns
        -------
        None
        """
        if label == Defender.HIGH_SUSPICION_LABEL:
            if origin not in self.quarantinedNodes: self.quarantinedNodes.append(origin)
            out_edges = list(self.graph.out_edges(origin))
            self.graph.remove_edges_from(out_edges)
        else:
            self.graph.remove_edge(origin, destination)
    

    def infectNode(self, destination):
        """Marks a node as infected if not previously infectged
        Parameters
        ----------
        destination
            IP of the receipent of the infected message

        Returns
        -------
        None
        """
        if destination not in self.infectedNodes:
            self.infectedNodes.append(destination)

    def calculateNodeInfectionReward(self, node):
        """Calculates reward for infecting the specified node
        Parameters
        ----------
        node
            node from the graph representing an IoT device

        Returns
        -------
        score
            integer value representing the degree of that node to other non-infected nodes
        """
        if node in self.infectedNodes: return 0 # No reward if currently impossible to infect
        score = 1
        neighbors = self.graph.neighbors(node)
        score += len([neighbor for neighbor in neighbors if neighbor not in self.infectedNodes])
        return score

    def isReachable(self, node):
        """Determines if a node is reachable for infection
        Parameters
        ----------
        node
            node from the graph representing an IoT device

        Returns
        -------
        reachable
            boolean value stating whether the node is reachable by the infected nodes
        """
        if node in self.infectedNodes:
            return False

        for infectedNode in self.infectedNodes:
            if node in self.graph.neighbors(infectedNode): 
                return True

        return False

    def displayGraph(self, displayAttack= False):
        """Displays the current network colored by past suspicion scores
        Parameters
        ----------
        displayAttack
            boolean flag specifying whether or not to display the current attack on the graph 

        Returns
        -------
        None
        """
        infectedColorMap = [self.colorMap[node] for node in self.infectedNodes]
        notInfectedColorMap = [self.colorMap[node] for node in self.graph.nodes()]
  
        
        if displayAttack:
            colorFilter = lambda u,v: 'r' if (self.attackMessage != None and u == self.attackMessage.origin and v == self.attackMessage.destination) else 'k'
            weightFilter = lambda u,v: 2 if (self.attackMessage != None and u == self.attackMessage.origin and v == self.attackMessage.destination) else 1
            colors = [colorFilter(edge[0], edge[1]) for edge in self.graph.edges()]
            widths = [weightFilter(edge[0], edge[1]) for edge in self.graph.edges()]
        else:
            colors = ['k'] * len(self.graph.edges())
            widths = [1] * len(self.graph.edges())       

        sizeFilter = lambda x: GameEngine.NODE_SIZE if x not in self.infectedNodes else 1
        nodeSizes = [sizeFilter(node) for node in self.graph.nodes()]

        ax = plt.gca()
        if displayAttack and self.attackMessage != None: ax.set_title('Pre Round Setup : Attacking ' + str(self.attackMessage.destination))
        elif displayAttack: ax.set_title('Pre Round Setup : No Attack this Round')
        elif self.lastAttackerScore < 0: ax.set_title('Post Round Results : Attack Repulsed')
        elif self.lastAttackerScore > 0: ax.set_title('Post Round Results : Attack Successful')
        else: ax.set_title('Post Round Results')
        networkx.draw_circular(self.graph, nodelist= self.infectedNodes, node_shape= GameEngine.INFECTED_MARKER, node_color = infectedColorMap, with_labels= False, node_size= GameEngine.NODE_SIZE * 4)
        networkx.draw_circular(self.graph, node_shape= GameEngine.NOT_INFECTED_MARKER, node_color= notInfectedColorMap, with_labels=True, node_size= nodeSizes, edge_color= colors, width= widths)

        plt.show()
        plt.pause(GameEngine.GRAPH_DELAY)
        plt.clf()

    def calculateScore(self, message, label):
        """Calculates the reward earned for each player and updates lives
        Parameters
        ----------
        message
            message object that contains metadata about the message being inspected

       label
           String label representing the suspicion category the message falls into
        
        Returns
        -------
        attackerReward
            The score earned by the attacker
        
        defenderReward
            The score earned by the defender
        """
        attackerReward = self.calculateNodeInfectionReward(message.destination)
        defenderReward = len([edge for edge in self.graph.neighbors(message.destination)]) + 1
        if message.isMalicious() and label == Defender.HIGH_SUSPICION_LABEL:
            return [-attackerReward, defenderReward]
        elif message.isMalicious() and label == Defender.MEDIUM_SUSPICION_LABEL:
            return [(-attackerReward / 2), defenderReward]
        elif message.isMalicious():
            return [attackerReward, -defenderReward]
        elif not message.isMalicious() and label ==  Defender.HIGH_SUSPICION_LABEL:
            return [None, -defenderReward]
        elif not message.isMalicious() and label == Defender.MEDIUM_SUSPICION_LABEL:
            return [None, (-defenderReward / 2)]
        elif not message.isMalicious():
            return [None, defenderReward]

    def logGameResults(self):
        """Return average degree, clustering coefficient, and connectedness of infected vs non-infected graph"""

        # degreeCount = collections.Counter(degree_sequence)
        # deg, cnt = zip(*degreeCount.items())

        # fig, ax = plt.subplots()
        # plt.bar(deg, cnt, width=0.80, color="b")

        # plt.title("Degree Histogram")
        # plt.ylabel("Count")
        # plt.xlabel("Degree")
        # ax.set_xticks([d + 0.4 for d in deg])
        # ax.set_xticklabels(deg)
        # plt.show()

        networkFileName = self.networkPath.split('/')[-1]
        networkName = networkFileName.split('.')[0]

        try:
            defenderDegrees = [d for n, d in self.graph.degree() if n not in self.infectedNodes]
            avgDefenderDegree = round(sum(defenderDegrees) / len(defenderDegrees), 3)
        except:
            avgDefenderDegree = 0
        
        try:
            attackerDegrees = [d for n, d in self.graph.degree() if n in self.infectedNodes]
            avgAttackerDegree = round(sum(attackerDegrees) / len(attackerDegrees), 3)
        except:
            avgAttackerDegree = 0

        clusterings = networkx.clustering(self.graph)

        try:
            defenderClusterings = [clusterings[node] for node in clusterings if node not in self.infectedNodes]
            avgDefenderClusterings = round(sum(defenderClusterings) / len(defenderClusterings), 3)
        except:
            avgDefenderClusterings = 0

        try:    
            attackerClusterings = [clusterings[node] for node in clusterings if node in self.infectedNodes]
            avgAttackerClusterings = round(sum(attackerClusterings) / len(attackerClusterings), 3)
        except:
            avgAttackerClusterings = 0

        numNotInfectedNodes = len(self.graph.nodes()) - len(self.infectedNodes)
        numInfectedNodes = len(self.infectedNodes)

        with open(os.path.join(GameEngine.GAME_LOG_PATH), 'a+') as file:
            file.write(GameEngine.GAME_ROW_STRING.format(networkName,self.roundNumber,avgDefenderDegree,avgAttackerDegree,avgDefenderClusterings,avgAttackerClusterings,numNotInfectedNodes,numInfectedNodes))

    def train(self):
        """starts the training runs for each player
        Parameters
        ----------
        None
        
        Returns
        -------
        None
        """
        self.attacker.train()
        self.defender.train()
        self.attacker.saveModel()
        self.defender.saveModel()

if __name__ == "__main__":
    """Runs a specified number of games, training can be turned on via the train flag"""
    parser = argparse.ArgumentParser(description= 'Processes game parameters.')
    parser.add_argument('-ap', '--attackPath', type= str, default= "../datasets/defaultAttackDataset.csv", help= 'Path to the file of attack messages')
    parser.add_argument('-tp', '--trafficPath', type= str, default= "../datasets/defaultTrafficDataset.csv", help= 'Path to the file of background messages')
    parser.add_argument('-np', '--networkPath', type= str, default= "../networks/defaultNetwork.csv", help= 'Path to the file of network parameters for the game')
    parser.add_argument('-ep', '--episodes', type= int, default= 1, help= 'Number of games to be played')
    parser.add_argument('-t', '--train', action= 'store_true', help= 'Whether the agents should be training at the end of each game')
    parser.add_argument('-l', '--load', action= 'store_true', help= 'Whether previous models should be loaded in for this game')
    parser.add_argument('-nv', '--noVisualize', action= 'store_false', help= 'set this flag to turn off the game visualization')
    args = parser.parse_args()

    engine = GameEngine(trafficPath= args.trafficPath, attackPath= args.attackPath, networkPath= args.networkPath, loadModels= args.load, visualize= args.noVisualize)

    for episode in range(args.episodes):
        engine.initializeGame()
        print('Starting episode', episode)
        engine.runGame()
        print('Episode', episode, 'complete')
        engine.logGameResults()
        if args.train:
            engine.train()
            print('Training for episode', episode, 'complete')
